import asyncio
import json
import os

from typing import Dict, List, Tuple, Any, Awaitable
import httpx

SCAN_CHUNK_SIZE = 64
GET_INFO_NUM = 4

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


async def get_info(id: int, ignore_not_found=False, ignore_created=False) -> Info:
    r = None
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"https://www.ctfer.vip/api/problem/{id}/",
                headers={
                    "UserAgent": "Mozilla/5.0 (Linux; Android 10; Pixel 3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.141 Mobile Safari/537.36",
                    "Cookie": os.environ["NSSCTF_COOKIE"]
                }
            )
    except Exception:
        await asyncio.sleep(2)
        return await get_info(id, ignore_not_found, ignore_created)
    try:
        data = r.json()
    except Exception:
        raise Unknown("parse json failed")

    if data.get("code", None) == 402:
        raise NotLogin()
    if "data" not in data:
        if ignore_not_found:
            return {}
        raise NotFound()
    if "code" not in data:
        raise Unknown(f"code not found for id: {id}")
    if data["code"] == 201:
        if ignore_created:
            return {}
        raise CreatedButEmpty()
    if data["code"] != 200:
        raise Unknown(f"code is not 200 for id: {id}, data:{data}")
    try:
        d = data["data"]
        info = {
            "id": id,
            "title": d["title"],
            "desc": d["desc"],
            "tags": d["tag"],
            "point": d["point"],
            "likes": d["likes"],
            "level": d["level"],
            "solved": d["info"]["solved"],
            "wa": d["info"]["wa"],
        }
    except Exception:
        raise Unknown("parse info failed")
    return info


async def scan(context: ScanContext) -> Tuple[List[asyncio.Task[Info]], ScanContext | None]:
    l, r = context
    if r == None:
        try:
            _ = await get_info(l + SCAN_CHUNK_SIZE)
        except NotFound:
            new_context = (l, l + SCAN_CHUNK_SIZE)
            return await scan(new_context)
        except CreatedButEmpty:
            pass
        new_context = (l + SCAN_CHUNK_SIZE, None)
        return (
            [
                asyncio.Task(get_info(
                    i,
                    ignore_not_found=True,
                    ignore_created=True
                )) for i in range(l, l + SCAN_CHUNK_SIZE)
            ],
            new_context
        )
    if r - l == 1:
        return (
            [
                asyncio.Task(get_info(
                    i,
                    ignore_not_found=True,
                    ignore_created=True
                )) for i in range(l, r)
            ],
            None
        )
    mid = (l + r) // 2
    try:
        info = await get_info(mid)
    except NotFound:
        new_context = (l, mid)
        return await scan(new_context)
    return (
        [
            asyncio.Task(get_info(i, ignore_not_found=True)) for i in range(l, mid)
        ],
        (mid, r)
    )


# async def scan_all():
#     context = (1, None)
#     undone_tasks = []
#     while context:
#         tasks, context = await scan(context)
#         undone_tasks += tasks
#         done_tasks, undone_tasks = [task for task in tasks if task.done()], [task for task in tasks if not task.done()]
#         while not done_tasks:
#             done_tasks, undone_tasks = [task for task in tasks if task.done()], [task for task in tasks if not task.done()]
#         for task in done_tasks:
#             yield await task
#         print(f"{context=}")


async def scan_all(max_id=10000, early_stop=500):
    tasks: List[asyncio.Task] = []
    last_exist_info_id = 0
    for i in range(1, max_id):
        task = asyncio.create_task(
            get_info(i, ignore_created=True, ignore_not_found=True))
        tasks.append(task)
        while not [task for task in tasks if task.done()] and len(tasks) > GET_INFO_NUM:
            await asyncio.sleep(0)
        done_tasks, tasks = [task for task in tasks if task.done()], [
            task for task in tasks if not task.done()]
        for task in done_tasks:
            info = await task
            if info and info.get("id", None):
                last_exist_info_id = max(last_exist_info_id, info["id"])
            yield info
        if early_stop and i - last_exist_info_id > early_stop:
            return


async def main():
    infos = []
    async for info in scan_all():
        if not info:
            continue
        print(info.get("id"), info.get("title"))
        infos.append(info)
    with open("infos.json", "w") as f:
        json.dump(infos, f, indent=2, ensure_ascii=False)


async def test():
    async for info in scan_all():
        print(info)

if __name__ == "__main__":
    asyncio.run(main())
