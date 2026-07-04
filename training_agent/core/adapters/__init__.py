from core.adapters.feishu import FeishuAdapter
from core.adapters.qq import QQAdapter
from core.adapters.registry import register_adapter
from core.adapters.wechat import WechatAdapter


def init_adapters() -> None:
    register_adapter(FeishuAdapter())
    register_adapter(WechatAdapter())
    register_adapter(QQAdapter())
