from ...utils import *
from ...record import after_record_hook
from ..common import *
from ..handler import *
from ..asset import *
from ..draw import *
from ..sub import SekaiGroupSubHelper

md_update_group_sub = SekaiGroupSubHelper("update", "MasterData更新通知", ALL_SERVER_REGIONS)

# ======================= 指令处理 ======================= #

pjsk_update = SekaiCmdHandler([
    "/pjsk update", "/pjsk_update", "/pjsk refresh", "/pjsk_refresh",
])
pjsk_update.check_cdrate(cd).check_wblist(gbl)
@pjsk_update.handle()
async def _(ctx: SekaiHandlerContext):
    mgr = RegionMasterDbManager.get(ctx.region)
    msg = f"{get_region_name(ctx.region)}MasterData数据源"
    for source in await mgr.get_all_sources(force_update=True):
        msg += f"\n[{source.name}] {source.version}"
    return await ctx.asend_reply_msg(msg.strip())


ngword = SekaiCmdHandler([
    "/pjsk ng", "/pjsk ngword", "/pjsk ng word",
    "/pjsk屏蔽词", "/pjsk屏蔽", "/pjsk敏感", "/pjsk敏感词",
])
ngword.check_cdrate(cd).check_wblist(gbl)
@ngword.handle()
async def _(ctx: SekaiHandlerContext):
    text = ctx.get_args()
    assert_and_reply(text, "请输入要查询的文本")
    words = await ctx.md.ng_words.get()
    def check():
        ret = []
        for word in words:
            if word in text:
                ret.append(word)
        return ret
    ret = await run_in_pool(check)
    if ret:
        await ctx.asend_reply_msg(f"检测到屏蔽词：{', '.join(ret)}")
    else:
        await ctx.asend_reply_msg("未检测到屏蔽词")


upload_help = SekaiCmdHandler([
    "/抓包帮助", "/抓包", "/pjsk upload help"
])
upload_help.check_cdrate(cd).check_wblist(gbl)
@upload_help.handle()
async def _(ctx: SekaiHandlerContext):
    text = Path(f"{SEKAI_DATA_DIR}/upload_help.txt").read_text(encoding="utf-8")
    return await ctx.asend_msg(text.strip())


# ======================= 定时通知 ======================= #

# masterdata更新通知
@RegionMasterDbManager.on_update()
async def send_masterdata_update_notify(
    region: str, source: str,
    version: str, last_version: str,
    asset_version: str, last_asset_version: str,
):
    bot = get_bot()
    region_name = get_region_name(region)

    # 防止重复通知
    last_notified_version = file_db.get(f"last_notified_md_version_{region}", None)
    if last_notified_version and get_version_order(last_notified_version) >= get_version_order(version):
        return
    file_db.set(f"last_notified_md_version_{region}", version)

    msg = f"从{source}获取{region_name}的MasterData版本更新: {last_version} -> {version}\n"
    if last_asset_version != asset_version:
        msg += f"解包资源版本: {last_asset_version} -> {asset_version}\n"
    msg = msg.strip()

    for group_id in md_update_group_sub.get_all(region):
        if not gbl.check_id(group_id): continue
        try:
            await send_group_msg_by_bot(bot, group_id, msg)
        except Exception as e:
            logger.print_exc(f"在群聊发送 {group_id} 发送 {region} MasterData更新通知失败")
            continue
