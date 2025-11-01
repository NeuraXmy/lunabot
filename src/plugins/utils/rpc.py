from .utils import *
import aiorpcx


_rpc_handlers = {}

def rpc_method(service_name: str, method_name: str):
    """
    装饰器，用于注册RPC方法处理程序。
    """
    def decorator(func):
        _rpc_handlers[service_name + "." + method_name] = func
        return func
    return decorator


class RpcSession(aiorpcx.RPCSession):
    def __init__(
        self, 
        name: str, 
        logger: Logger, 
        *args, 
        on_connect: Callable = None,
        on_disconnect: Callable = None,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.id = str(self.remote_address())
        self.name = name
        self.logger = logger
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect

        self.on_connect(self)
        logger.info(f'{self.name}RPC服务的客户端 {self.id} 连接成功')

    async def connection_lost(self):
        await super().connection_lost()
        self.on_disconnect(self)
        self.logger.info(f'{self.name}RPC服务的客户端 {self.id} 断开连接')

    async def handle_request(self, request):
        self.logger.debug(f'收到{self.name}RPC服务的客户端 {self.id} 的请求 {request}')
        handler = _rpc_handlers.get(self.name + "." + request.method)
        request.args = [self.id] + request.args
        coro = aiorpcx.handler_invocation(handler, request)()
        self.logger.debug(f'{self.name}RPC服务的客户端 {self.id} 的请求 {request} 返回: {coro}')
        return await coro
    

def get_session_factory(
    name: str, 
    logger: Logger, 
    on_connect: Callable = None,
    on_disconnect: Callable = None,
):
    def factory(*args, **kwargs):
        return RpcSession(name, logger, *args, on_connect=on_connect, on_disconnect=on_disconnect, **kwargs)
    return factory


@staticmethod
def start_rpc_service(
    host: str, 
    port: int,
    name: str, 
    logger: Logger, 
    on_connect: Callable = None,
    on_disconnect: Callable = None, 
):
    """
    启动RPC服务。
    Parameters:
        name (str): 服务名称。
        logger (Logger): 用于输出日志的Logger实例。
        on_connect (Callable): 客户端连接时调用的回调函数，接受一个参数（会话实例）。
        on_disconnect (Callable): 客户端断开连接时调用的回调函数，接受一个参数（会话实例）。
        host (str): 服务器主机地址。
        port (int): 服务器端口号。
    """
    @async_task(f'{name}RPC服务', logger)
    async def _():
        try:
            async with aiorpcx.serve_ws(
                get_session_factory(name, logger, on_connect, on_disconnect), 
            host, port):
                logger.info(f'{name}RPC服务已启动 ws://{host}:{port}')
                await asyncio.sleep(1e9)
        except asyncio.exceptions.CancelledError:
            logger.info(f'{name}RPC服务已关闭')