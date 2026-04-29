from typing import Literal
import os

PROJECT_NAME = 'wxauto4'
VERSION = '41.1.2'

DEFAULT_STICKERS = [
    '[微笑]', '[撇嘴]', '[色]', '[发呆]', '[得意]', '[流泪]', '[害羞]', '[闭嘴]', '[睡]', '[大哭]', 
    '[尴尬]', '[发怒]', '[调皮]', '[呲牙]', '[惊讶]', '[难过]', '[囧]', '[抓狂]', '[吐]', '[偷笑]', 
    '[愉快]', '[白眼]', '[傲慢]', '[困]', '[惊恐]', '[憨笑]', '[悠闲]', '[咒骂]', '[疑问]', '[嘘]', 
    '[晕]', '[衰]', '[骷髅]', '[敲打]', '[再见]', '[擦汗]', '[抠鼻]', '[鼓掌]', '[坏笑]', '[右哼哼]', 
    '[鄙视]', '[委屈]', '[快哭了]', '[阴险]', '[亲亲]', '[可怜]', '[笑脸]', '[生病]', '[脸红]', '[破涕为笑]', 
    '[恐惧]', '[失望]', '[无语]', '[嘿哈]', '[捂脸]', '[奸笑]', '[机智]', '[皱眉]', '[耶]', '[吃瓜]', 
    '[加油]', '[汗]', '[天啊]', '[Emm]', '[社会社会]', '[旺柴]', '[好的]', '[打脸]', '[哇]', '[翻白眼]', 
    '[666]', '[让我看看]', '[叹气]', '[苦涩]', '[裂开]', '[嘴唇]', '[爱心]', '[心碎]', '[拥抱]', '[强]', 
    '[弱]', '[握手]', '[胜利]', '[抱拳]', '[勾引]', '[拳头]', '[OK]', '[合十]', '[啤酒]', '[咖啡]', 
    '[蛋糕]', '[玫瑰]', '[凋谢]', '[菜刀]', '[炸弹]', '[便便]', '[月亮]', '[太阳]', '[庆祝]', '[礼物]', 
    '[红包]', '[發]', '[福]', '[烟花]', '[爆竹]', '[猪头]', '[跳跳]', '[发抖]', '[转圈]', '[天啊]', 
    '[强]', '[汗]', '[握手]', 
]

class WxParam:
    # 语言设置
    LANGUAGE: Literal['cn', 'cn_t', 'en'] = 'cn'

    # 是否启用日志文件
    ENABLE_FILE_LOGGER: bool = True

    # 下载文件/图片默认保存路径
    DEFAULT_SAVE_PATH: str = os.path.join(os.getcwd(), 'wxautox文件下载')

    # 是否启用消息哈希值用于辅助判断消息，开启后会稍微影响性能
    MESSAGE_HASH: bool = False

    # 头像到消息X偏移量，用于消息定位，点击消息等操作
    DEFAULT_MESSAGE_XBIAS = 51
    DEFAULT_MESSAGE_YBIAS = 30

    # 是否强制重新自动获取X偏移量，如果设置为True，则每次启动都会重新获取
    FORCE_MESSAGE_XBIAS: bool = False

    # 监听消息时间间隔，单位秒
    LISTEN_INTERVAL: int = 1

    # 监听执行器线程池大小
    LISTENER_EXCUTOR_WORKERS: int = 4

    # 搜索聊天对象超时时间，单位秒
    SEARCH_CHAT_TIMEOUT: int = 2

    # 微信笔记加载超时时间，单位秒
    NOTE_LOAD_TIMEOUT: int = 30

    # 发送文件超时时间，单位秒
    SEND_FILE_TIMEOUT: int = 10

    # 监听尺寸，越大越好
    # 由于4.x版本客户端的ui机制是显示的部分才注册uia控件
    # 所以尽可能拉大窗口显示更多消息来提高判断容错
    CHAT_WINDOW_SIZE = (800, 6000)

    # 输入内容相似度，用于判断输入框中的内容是否要发送的内容，避免发送错误内容
    # 因为存在特殊符号转码问题，可能编辑框内容无法100%与实际传入的字符串相等
    # 所以达到相似度即通过校验，才触发发送
    SEND_CONTENT_RATIO = 0.9

    # GetNextNewMessage方法最大获取数量
    # 太多的话可能导致获取时间太久无法 
    GET_NEXT_MAX_QUANTITY = 30

    # GetNextNewMessage方法最长获取时间，单位秒
    GET_NEXT_MAX_RUNTIME = 10

    # 特殊聊天会话
    SPECIAL_SESSION_NAME = ['公众号', '折叠的聊天', 'QQ邮箱提醒', '服务号']

    # 默认聊天表情
    DEFAULT_STICKERS = DEFAULT_STICKERS

    # 回调函数结束标识
    CALLBACK_STOP_SIGN = 'stop'

    # @成员输入间隔时间，单位秒
    INPUT_AT_INTERVAL = 0.5

class WxResponse(dict):
    def __init__(self, status: str, message: str, data: dict = None):
        super().__init__(status=status, message=message, data=data)

    def __str__(self):
        return str(self.to_dict())
    
    def __repr__(self):
        return str(self.to_dict())

    def to_dict(self):
        return {
            'status': self['status'],
            'message': self['message'],
            'data': self['data']
        }

    def __bool__(self):
        return self.is_success
    
    @property
    def is_success(self):
        return self['status'] == '成功'

    @classmethod
    def success(cls, message=None, data: dict = None):
        return cls(status="成功", message=message, data=data)

    @classmethod
    def failure(cls, message: str, data: dict = None):
        return cls(status="失败", message=message, data=data)

    @classmethod
    def error(cls, message: str, data: dict = None):
        return cls(status="错误", message=message, data=data)