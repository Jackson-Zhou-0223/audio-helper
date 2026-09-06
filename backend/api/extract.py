from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Body, Request

from schemas import ExtractRequest, SuccessResponse
from services.extract import extract_meetup

logger = logging.getLogger(__name__)
router = APIRouter()

EXTRACT_EXAMPLES = {
    "normal": {
        "summary": "正常提取",
        "description": "模型原始输出含 party_count 与 incomplete_reason；接口成功只返回五个业务字段。",
        "value": {
            "text": "我在杭州东站，朋友在西湖龙翔桥地铁站，帮我们找个中间的咖啡店。",
            "city": "杭州",
        },
    },
    "page_city": {
        "summary": "未说城市，使用页面城市",
        "description": "口述无城市时，用请求里的 city。模型城市字段可能先为 null，接口补成页面城市后返回五个字段。",
        "value": {
            "text": "我在东站，朋友在西湖龙翔桥地铁站，帮我们找个中间的咖啡店。",
            "city": "杭州",
        },
    },
    "spoken_city_first": {
        "summary": "口述城市优先于页面默认城市",
        "description": "页面是杭州，口述是宁波。模型应输出宁波；接口五个字段也是宁波，不能改回杭州。",
        "value": {
            "text": "我在宁波火车站，朋友在天一广场，帮我们找个中间的咖啡店。",
            "city": "杭州",
        },
    },
    "category": {
        "summary": "类别归一化",
        "description": "口述「喝咖啡」。模型或后端归一化为「咖啡店」后，接口 category 为咖啡店。",
        "value": {
            "text": "我在杭州东站，朋友在西湖龙翔桥地铁站，帮我们找个中间喝咖啡的地方。",
            "city": "杭州",
        },
    },
    "missing_address": {
        "summary": "地址缺失",
        "description": "模型结构合法，address 可为 null。接口返回 422 EXTRACT_INCOMPLETE，不是模型格式异常。",
        "value": {
            "text": "我在杭州东站，帮我们找个中间的咖啡店。",
            "city": "杭州",
        },
    },
    "vague_home": {
        "summary": "含糊表达（我家）",
        "description": "模型不要猜我家的具体地址，address 填 null。接口 422 EXTRACT_INCOMPLETE。",
        "value": {
            "text": "我在我家，朋友在西湖龙翔桥地铁站，帮我们找个中间的咖啡店。",
            "city": "杭州",
        },
    },
    "party_count": {
        "summary": "人数不符",
        "description": "模型 party_count 不为 2。接口 422 PARTY_COUNT_INVALID，不返回五个业务字段。",
        "value": {
            "text": "我在杭州东站，小李在龙翔桥，小王在城西银泰，帮我们三个人找个中间的咖啡店。",
            "city": "杭州",
        },
    },
    "cross_city": {
        "summary": "跨城",
        "description": "模型可输出两个不同城市。接口 422 CROSS_CITY。杭州与杭州市不算跨城。",
        "value": {
            "text": "我在杭州东站，朋友在宁波火车站，帮我们找个中间的咖啡店。",
            "city": "杭州",
        },
    },
}


@router.post(
    "/extract",
    response_model=SuccessResponse,
    summary="地址与需求提取",
)
async def extract(
    request: Request,
    body: Annotated[ExtractRequest, Body(openapi_examples=EXTRACT_EXAMPLES)],
) -> dict:
    data = await extract_meetup(body.text, body.city)
    logger.info("extract complete category=%s", data.category)
    return {
        "request_id": request.state.request_id,
        "data": data.model_dump(),
    }
