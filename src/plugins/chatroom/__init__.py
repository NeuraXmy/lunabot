from nonebot.adapters.onebot.v11.message import Message as OutMessage
from ..record.sql import query_recent_msg
from ..record import before_record_hook
from ..utils import *
from ..utils.rpc import *


config = Config('chatroom')
logger = get_logger("Chatroom")
file_db = get_file_db("data/chatroom/db.json", logger)

def process_msg(msg):
    if isinstance(msg['time'], datetime):
        msg['time'] = msg['time'].timestamp()
    pass

def get_md5(s):
    import hashlib
    m = hashlib.md5()
    m.update(s.encode())
    return m.hexdigest()

# ------------------------------ 新聊天 ------------------------------ #

# 为每个客户端分别存储的新消息
message_pool = {}

# 记录新消息
@before_record_hook
async def record_new_message(bot, event):
    if not is_group_msg(event): return
    msg_obj = await get_msg_obj(bot, event.message_id)
    group_id = event.group_id
    user_name = await get_group_member_name(bot, group_id, event.user_id)

    for cid, group_msgs in message_pool.items():
        # print(f"add msg {event.message_id} of group {group_id} to {cid}")
        if group_id not in group_msgs:
            group_msgs[group_id] = []
        group_msgs[group_id].append({
            'msg_id': event.message_id,
            'time': event.time,
            'user_id': event.user_id,
            'nickname': user_name,
            'msg': msg_obj['message'],
        })

# ------------------------------ RPC Handler ------------------------------ #
        
SERVICE = 'chatroom'

def on_connect(session: RpcSession):
    message_pool[session.id] = {}

def on_disconnect(session: RpcSession):
    if session.id in message_pool:
        del message_pool[session.id]

start_rpc_service(
    host=config.get('host'),
    port=config.get('port'),
    name=SERVICE,
    logger=logger,
    on_connect=on_connect,
    on_disconnect=on_disconnect
)
        

# echo测试
@rpc_method(SERVICE, 'echo')
async def handle_echo(cid, message):
    return f'{cid} {message}'

# 延迟echo测试
@rpc_method(SERVICE, 'echo_delay')
async def handle_echo_delay(cid, message, delay):
    await asyncio.sleep(delay)
    return f'{cid} {message}'

# 获取群组列表
@rpc_method(SERVICE, 'get_group_list')
async def handle_get_group_list(cid):
    bot = get_bot()
    return await get_group_list(bot)

# 获取群组信息
@rpc_method(SERVICE, 'get_group')
async def handle_get_group(cid, group_id):
    bot = get_bot()
    return await get_group(bot, group_id)

# 发送群消息
@rpc_method(SERVICE, 'send_group_msg')
async def handle_send_group_msg(cid, group_id, message):
    bot = get_bot()
    if isinstance(message, str):
        message=OutMessage(message)
    return await bot.send_group_msg(group_id=int(group_id), message=message)

# 从数据库获取群聊天记录
@rpc_method(SERVICE, 'get_group_history_msg')
async def handle_get_group_msg(cid, group_id, limit):
    msgs = await query_recent_msg(group_id, limit)
    for msg in msgs:
        process_msg(msg)
    return msgs

# 获取群新消息，获取后清空
@rpc_method(SERVICE, 'get_group_new_msg')
async def handle_get_group_new_msg(cid, group_id):
    group_id = int(group_id)
    if group_id not in message_pool[cid]:
        return []
    new_msg = message_pool[cid][group_id]
    message_pool[cid][group_id] = []
    for msg in new_msg:
        process_msg(msg)
    return new_msg

# 获取客户端数据
@rpc_method(SERVICE, 'get_client_data')
async def handle_get_client_data(cid, name):
    try:
        return load_json(f'data/chatroom/client_data/{name}.json')
    except:
        return None
    
# 设置客户端数据
@rpc_method(SERVICE, 'set_client_data')
async def handle_set_client_data(cid, name, data):
    dump_json(data, f'data/chatroom/client_data/{name}.json')
    return True

# 获取消息
@rpc_method(SERVICE, 'get_msg')
async def handle_get_msg(cid, msg_id):
    bot = get_bot()
    msg_obj = await get_msg_obj(bot, msg_id)
    return {
        'msg_id': msg_obj['message_id'],
        'time': msg_obj['time'],
        'user_id': msg_obj['sender']['user_id'],
        'nickname': msg_obj['sender']['nickname'],
        'msg': msg_obj['message'],
    }

# 获取转发消息
@rpc_method(SERVICE, 'get_forward_msg')
async def handle_get_forward_msg(cid, forward_id):
    bot = get_bot()
    msgs = (await get_forward_msg(bot, forward_id))['messages']
    return [{
        'msg_id': msg['message_id'],
        'time': msg['time'],
        'user_id': msg['sender']['user_id'],
        'nickname': msg['sender']['nickname'],
        'msg': msg['content'],
    } for msg in msgs]

group_msg_segments = {}

# 清空分段消息
@rpc_method(SERVICE, 'clear_group_msg_split')
async def handle_clear_group_msg_split(cid):
    if cid in group_msg_segments:
        del group_msg_segments[cid]
    return True

# 上传分段发送群消息的片段
@rpc_method(SERVICE, 'upload_group_msg_split')
async def handle_upload_group_msg_split(cid, message, index):
    if cid not in group_msg_segments:
        group_msg_segments[cid] = {}
    segments = group_msg_segments[cid]
    segments[index] = message
    return len(segments)
    
# 连接片段并发送
@rpc_method(SERVICE, 'send_group_msg_split')
async def handle_send_group_msg_split(cid, group_id, md5, is_str):
    segments = group_msg_segments[cid]
    message = ''.join([segments[i] for i in range(len(segments))])
    del group_msg_segments[cid]
    if get_md5(message) != md5:
        raise Exception("MD5 Verification Failed")
    if not is_str:
        message = loads_json(message)
    else:
        message = OutMessage(message)
    bot = get_bot()
    return await bot.send_group_msg(group_id=int(group_id), message=message)