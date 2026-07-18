from harness.tools.registry import ToolDefinition

WEATHER = {
    "北京": "晴，15-25°C，东南风 2 级",
    "上海": "多云，18-22°C，西南风 3 级",
    "深圳": "阵雨，22-28°C，南风 2 级",
    "广州": "多云转晴，20-28°C，东风 3 级",
    "杭州": "晴，14-24°C，北风 2 级",
    "成都": "阴，16-22°C，微风",
}


async def _weather(args: dict) -> str:
    return WEATHER.get(args["city"], f"{args['city']}：暂无数据")


async def _calculator(args: dict) -> str:
    expression = args["expression"]
    try:
        result = eval(expression, {"__builtins__": {}}, {})
        return f"{expression} = {str(result).lower() if isinstance(result, bool) else result}"
    except Exception:
        return f"无法计算: {expression}"


weather_tool = ToolDefinition(
    "get_weather",
    "查询指定城市的天气信息",
    {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "城市名称"}},
        "required": ["city"],
        "additionalProperties": False,
    },
    _weather,
    True,
    True,
)
calculator_tool = ToolDefinition(
    "calculator",
    "计算数学表达式的结果",
    {
        "type": "object",
        "properties": {"expression": {"type": "string", "description": '数学表达式，如 "2 + 3 * 4"'}},
        "required": ["expression"],
        "additionalProperties": False,
    },
    _calculator,
    True,
    True,
)
