import asyncio
import json
import os
import random
from typing import Dict, List, Tuple, Any
import httpx
from anyio import EndOfStream

SCAN_CHUNK_SIZE = 64
GET_INFO_NUM = 16
COOKIES = {}
IdLeft = int  # Id大于等于的序号
IdRight = int | None  # Id小于的序号
Info = Dict[str, Any]
ScanContext = Tuple[IdLeft, IdRight]


class NotLogin(Exception):
    pass


class NotFound(Exception):
    pass


class CreatedButEmpty(Exception):
    pass


class Unknown(Exception):
    pass


USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 10; Pixel 3) AppleWebKit/537.36 "
    + "(KHTML, like Gecko) Chrome/87.0.4280.141 Mobile Safari/537.36"
)


async def login():
    """使用账号密码登陆

    Returns:
        _type_: _description_
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://www.nssctf.cn/api/user/login/",
            headers={"User-Agent": USER_AGENT},
            data={
                "username": os.environ["NSSCTF_USERNAME"],
                "password": os.environ["NSSCTF_PASSWORD"],
            },
        )
        cookies = dict(resp.cookies)
        cookies["token"] = resp.json()["data"]["token"]
        return cookies


async def get_info(
    info_id: int, ignore_not_found=False, ignore_created=False
) -> Info | None:
    """根据id获取对应题目的信息

    Args:
        info_id (int): id
        ignore_not_found (bool, optional): 找不到时返回空. Defaults to False.
        ignore_created (bool, optional):
            忽略CreatedButNotFound的情况. Defaults to False.

    Raises:
        NotLogin: 没有登陆
        NotFound: 没有找到
        CreatedButEmpty: 找到了，但是为空
        Unknown: 未知

    Returns:
        Info | None: 返回的信息
    """
    resp = None
    try:
        async with httpx.AsyncClient(cookies=COOKIES) as client:
            resp = await client.get(
                f"https://www.nssctf.cn/api/problem/v2/{info_id}/",
                headers={
                    "UserAgent": USER_AGENT,
                    # "Cookie": os.environ["NSSCTF_COOKIE"],
                },
            )
    except (httpx.HTTPError, EndOfStream) as exc:
        print(f"error: {type(exc)} {exc}")
        await asyncio.sleep(2)
        return await get_info(info_id, ignore_not_found, ignore_created)
    try:
        data = resp.json()
    except Exception as exc:
        raise Unknown("parse json failed") from exc
    if data.get("code", None) == 402:
        raise NotLogin()
    if "data" not in data:
        if ignore_not_found:
            return None
        raise NotFound()
    if "code" not in data:
        raise Unknown(f"code not found for id: {info_id}")
    if data["code"] == 201:
        if ignore_created:
            return None
        raise CreatedButEmpty()
    if data["code"] != 200:
        raise Unknown(f"code is not 200 for id: {info_id}, data:{data}")
    try:
        info_data = data["data"]
        info = {
            "id": info_id,
            "title": info_data["title"],
            "desc": info_data["desc"],
            "tags": [tag_info[0] for tag_info in info_data["tag"]],
            "point": info_data["point"],
            "likes": info_data["likes"],
            "level": info_data["level"],
            "solved": info_data["info"]["solved"],
            "wa": info_data["info"]["wa"],
        }
    except Exception as exc:
        raise Unknown("parse info failed") from exc
    return info


async def task_slide_window(coro_gen, window_size):
    """从coro_gen中迭代协程，创建并执行对应的task, 并yield结果"""
    tasks: List[asyncio.Task] = []
    for coro in coro_gen:
        task = asyncio.create_task(coro)
        tasks.append(task)
        while (
            not [task for task in tasks if task.done()]
            and len(tasks) > window_size
        ):
            await asyncio.sleep(0)
        done_tasks, tasks = [task for task in tasks if task.done()], [
            task for task in tasks if not task.done()
        ]
        for task in done_tasks:
            yield await task


async def scan_all(from_id=1, max_id=10000, early_stop=500):
    """扫描整个网站

    Args:
        max_id (int, optional): 扫描使用的最大id. Defaults to 10000.
        early_stop (int, optional): 有多少个无效ID则提早停止. Defaults to 500.

    Yields:
        Info: 扫描到的题目信息
    """
    nonexist_count = 0

    def coro_gen():
        for i in range(from_id, max_id):
            coro = get_info(i, ignore_created=True, ignore_not_found=True)
            should_stop = yield coro
            if should_stop:
                break

    gen = coro_gen()
    async for info in task_slide_window(gen, window_size=GET_INFO_NUM):
        if info and info.get("id", None):
            yield info
        else:
            nonexist_count += 1
        if nonexist_count > early_stop:
            try:
                _ = gen.send(True)
            except StopIteration:
                pass


async def main():
    """异步爬虫的入口"""
    global COOKIES
    infos = []
    with open("infos.json", "r", encoding="utf-8") as file:
        infos: List[Info] = json.load(file)
    ids = set(info["id"] for info in infos)
    current_max_id = max(ids)
    print(f"max id of now: {current_max_id}")

    # 登陆
    COOKIES = await login()

    # 刷新已经有了的ID
    target_id_digit = random.randint(0, 9)
    coros = (get_info(i) for i in ids if i % 10 == target_id_digit)
    refreshed_infos: List[Info] = []
    refreshed_ids = set()

    async for info in task_slide_window(coros, window_size=GET_INFO_NUM):
        if info is None:
            continue
        print(info.get("id"), info.get("title"))
        refreshed_infos.append(info)
        refreshed_ids.add(info["id"])

    infos = [
        info for info in infos if info["id"] not in refreshed_ids
    ] + refreshed_infos
    infos.sort(key=lambda info: info["id"])

    # 获取当前没有的题目
    async for info in scan_all(from_id=current_max_id):
        if not info:
            continue
        print(info.get("id"), info.get("title"))
        infos.append(info)

    with open("infos.json", "w", encoding="utf-8") as file:
        json.dump(infos, file, indent=2, ensure_ascii=False)


async def test():
    """测试函数入口"""
    info = await get_info(382)
    print(info)


if __name__ == "__main__":
    asyncio.run(main())
