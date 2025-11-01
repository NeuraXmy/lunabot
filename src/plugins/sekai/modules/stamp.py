from ...utils import *
from ..common import *
from ..handler import *
from ..asset import *
from ..draw import *
from .stamp_maker import make_stamp, STAMP_MAKER_BASE_DIR
from ...imgtool import cutout_image, shrink_image
from ...llm import ChatSession, ChatSessionResponse, get_model_preset

GIF_STAMP_SCALE_CFG = config.item('stamp.gif_scale')
STAMP_BASE_IMAGE_DIR = f"{STAMP_MAKER_BASE_DIR}/images"
STAMP_CUTOUT_IMAGE_DIR = f"{STAMP_MAKER_BASE_DIR}/cutouts"
cutout_ratelimit = RateLimit(file_db, logger, config.item('stamp.cutout.daily_limit'), 'd', rate_limit_name='pjsk_stamp_cutout')

# ======================= 处理逻辑 ======================= #

# 获取表情图片
async def get_stamp_image(ctx: SekaiHandlerContext, sid) -> Image.Image:
    stamp = await ctx.md.stamps.find_by_id(sid)
    assert_and_reply(stamp, f"表情 {sid} 不存在")
    asset_name = stamp['assetbundleName']
    img = await ctx.rip.img(f"stamp/{asset_name}_rip/{asset_name}.png")
    return img

# 获取用于发送的透明表情cq码
async def get_stamp_image_cq(ctx: SekaiHandlerContext, sid: int, format: str) -> str:
    assert format in ["png", "gif"]
    if format == "gif":
        with TempFilePath("gif") as path:
            img = await get_stamp_image(ctx, sid)
            scale = GIF_STAMP_SCALE_CFG.get()
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.Resampling.LANCZOS).convert("RGBA")
            # 将图片中半透明像素处理为白底的不透明像素
            img = np.array(img)
            alpha_channel = img[:, :, 3] / 255.0
            alpha_mask = alpha_channel >= 0.1
            for c in range(3):
                img[:, :, c] = np.where(
                    alpha_mask,
                    (img[:, :, c] * alpha_channel + 255 * (1 - alpha_channel)).astype(np.uint8),
                    img[:, :, c]
                )
            img[:, :, 3] = np.where(alpha_mask, 255, img[:, :, 3])
            img = Image.fromarray(img)
            save_transparent_static_gif(img, path, alpha_threshold=0.1)
            return await get_image_cq(path)
    else:
        return await get_image_cq(await get_stamp_image(ctx, sid))

# 合成某个角色的所有表情图片
async def compose_character_all_stamp_image(ctx: SekaiHandlerContext, cid):
    stamp_ids = []
    for stamp in await ctx.md.stamps.get():
        if stamp.get('characterId1') == cid or stamp.get('characterId2') == cid:
            stamp_ids.append(stamp['id'])
    stamp_imgs = await asyncio.gather(*[get_stamp_image(ctx, sid) for sid in stamp_ids])
    stamp_id_imgs = [(sid, img) for sid, img in zip(stamp_ids, stamp_imgs) if img]

    with Canvas(bg=SEKAI_BLUE_BG).set_padding(BG_PADDING) as canvas:
        with VSplit().set_sep(8).set_item_align('l').set_bg(roundrect_bg()).set_padding(8):
            TextBox(
                f"发送\"{ctx.original_trigger_cmd} 序号\"获取单张表情\n"
                f"发送\"{ctx.original_trigger_cmd} 序号 文本\"制作表情\n"
                f"序号为绿色的表情有人工抠图处理的底图\n"
                f"序号为蓝色的表情有AI抠图处理的底图",
                style=TextStyle(font=DEFAULT_FONT, size=24, color=(0, 0, 0, 255)), use_real_line_count=True) \
                .set_padding(16).set_bg(roundrect_bg())
            with Grid(col_count=5).set_sep(4, 4).set_item_bg(roundrect_bg()):
                for sid, img in stamp_id_imgs:
                    text_color = (200, 0, 0, 255)
                    if res := await ensure_stamp_maker_base_image(ctx, sid, use_cutout=False):
                        p, info = res
                        if p and not info:
                            text_color = (0, 150, 0, 255)
                        elif p and info:
                            text_color = (0, 0, 200, 255)
                    with VSplit().set_padding(4).set_sep(4):
                        ImageBox(img, size=(None, 100), use_alphablend=True, shadow=True)
                        TextBox(str(sid), style=TextStyle(font=DEFAULT_BOLD_FONT, size=24, color=text_color))
    add_watermark(canvas)
    return await canvas.get_img()

# 制作表情并返回cq码
async def make_stamp_image_cq(ctx: SekaiHandlerContext, sid: int, text: str, format: str) -> str:
    stamp = await ctx.md.stamps.find_by_id(sid)
    assert_and_reply(stamp, f"表情 {sid} 不存在")
    cid = stamp.get('characterId1')
    cid2 = stamp.get('characterId2')
    assert_and_reply(cid and not cid2, f"该表情不支持制作")
    nickname = get_character_first_nickname(cid)
    text_zoom_ratio = 1.0
    line_count = 0
    for line in text.splitlines():
        dst_len = get_str_display_length(line)
        text_zoom_ratio = min(text_zoom_ratio, 0.3 + dst_len * 0.04)
        line_count += 1
    text_y_offset = int(15 - 30 * (1.0 - text_zoom_ratio))

    base_image_path, addtional_info = await ensure_stamp_maker_base_image(ctx, sid, use_cutout=True)

    img = make_stamp(
        base_image_path = base_image_path,
        character = nickname, 
        text = text,
        degree = 5,
        text_zoom_ratio = text_zoom_ratio,
        text_pos = "mu",
        line_spacing = 0,
        text_x_offset = 0,
        text_y_offset = text_y_offset,
        disable_different_font_size = False
    )
    if format == 'gif':
        scale = GIF_STAMP_SCALE_CFG.get()
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.Resampling.LANCZOS)
        with TempFilePath("gif") as path:
            save_transparent_static_gif(img, path)
            return await get_image_cq(path) + addtional_info
    else:
        return await get_image_cq(img) + addtional_info

# 检查某个表情是否有用于制作的底图，没有底图的情况可以请求LLM抠图或返回None，返回[底图路径,额外信息]
async def ensure_stamp_maker_base_image(ctx: SekaiHandlerContext, sid: int, use_cutout: bool) -> tuple[str, str] | None:
    await ctx.block(f"sid={sid}")
    filename = f"{sid:06d}.png"
    base_image_path = f"{STAMP_BASE_IMAGE_DIR}/{filename}"
    if os.path.isfile(base_image_path):
        return base_image_path, ""
    cutout_image_path = f"{STAMP_CUTOUT_IMAGE_DIR}/{filename}"
    cutout_info = f"该表情底图使用AI自动抠图，若抠图错误可使用\"/pjsk表情刷新{sid}\"重新抠图"
    if os.path.isfile(cutout_image_path):
        return cutout_image_path, cutout_info
    
    if not use_cutout:
        return None
    
    if not config.get('stamp.cutout.enable'):
        raise ReplyException(f"表情{sid}没有可用的底图")
    
    if not await cutout_ratelimit.check(ctx.event):
        raise NoReplyException()
    
    # 请求LLM抠图
    await ctx.asend_reply_msg(f"正在进行表情{sid}的AI抠图...")

    img = await get_stamp_image(ctx, sid)
    w, h = img.size
    black = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    black.alpha_composite(img)
    img = black

    model = get_model_preset('sekai.stamp_cutout')
    prompt = config.get('stamp.cutout.prompt')
    tolerance = config.get('stamp.cutout.tolerance')
    edge = config.get('stamp.cutout.edge')

    logger.info(f"请求LLM表情抠图 sid={sid}")
    session = ChatSession()
    session.append_user_content(prompt, [img])

    def process_resp(resp: ChatSessionResponse):
        assert resp.images, "LLM未返回抠图结果"
        return resp.images[0]

    image: Image.Image = await session.get_response(model, process_resp, image_response=True)
    image = image.resize((w, h), Image.Resampling.LANCZOS)

    image = await run_in_pool(cutout_image, image, tolerance)
    image = await run_in_pool(shrink_image, image, 0, edge)
    create_parent_folder(cutout_image_path)
    image.save(cutout_image_path)
    return cutout_image_path, cutout_info
    

# ======================= 指令处理 ======================= #

# 表情查询/制作
pjsk_stamp = SekaiCmdHandler(["/pjsk stamp", "/pjsk_stamp", "/pjsk表情", "/pjsk表情制作"])
pjsk_stamp.check_cdrate(cd).check_wblist(gbl)
@pjsk_stamp.handle()
async def _(ctx: SekaiHandlerContext):
    await ctx.block_region()

    args = ctx.get_args().strip()
    format = 'gif'
    if "png" in args:
        format = 'png'
        args = args.replace("png", "").strip()

    qtype, sid, cid, text = None, None, None, None

    # 尝试解析：全都是id
    if not qtype:
        try:
            assert all([int(x) >= 0 for x in args.split()])
            sid = [int(x) for x in args.split()]
            qtype = "id"
        except:
            pass

    # 尝试解析：单独昵称作为参数
    if not qtype:
        try:
            cid = get_cid_by_nickname(args)
            assert cid is not None
            qtype = "cid"
        except:
            pass

    # 尝试解析：id+文本作为参数
    if not qtype:
        try:
            sid, text = args.split(maxsplit=1)
            sid = int(sid)
            assert sid >= 0 and text
            qtype = "id_text"
        except:
            pass
    
    if not qtype:
        return await ctx.asend_reply_msg(f"""使用方式
根据id查询: {ctx.original_trigger_cmd} 123
查询多个: {ctx.original_trigger_cmd} 123 456
查询某个角色所有: {ctx.original_trigger_cmd} miku                                    
制作表情: {ctx.original_trigger_cmd} 123 文本
""".strip())
    
    # id获取表情
    if qtype == "id":
        logger.info(f"获取表情 sid={sid}")
        msg = "".join([await get_stamp_image_cq(ctx, x, format) for x in sid])
        return await ctx.asend_reply_msg(msg)
    
    # 获取角色所有表情
    if qtype == "cid":
        logger.info(f"合成角色表情: cid={cid}")
        msg = await get_image_cq(await compose_character_all_stamp_image(ctx, cid))
        return await ctx.asend_reply_msg(msg)

    # 制作表情
    if qtype == "id_text":
        logger.info(f"制作表情: sid={sid} text={text}")
        return await ctx.asend_reply_msg(await make_stamp_image_cq(ctx, sid, text, format))


# 随机表情 
pjsk_rand_stamp = SekaiCmdHandler([
    "/pjsk rand stamp", "/pjsk随机表情", "/pjsk随机表情制作", "/随机表情",
])
pjsk_rand_stamp.check_cdrate(cd).check_wblist(gbl)
@pjsk_rand_stamp.handle()
async def _(ctx: SekaiHandlerContext):
    await ctx.block_region()
    args = ctx.get_args().strip()
    format = 'gif'
    if "png" in args:
        format = 'png'
        args = args.replace("png", "").strip()

    async def get_rand_sid(cid, can_make):
        stamps = await ctx.md.stamps.get()
        for i in range(10000):
            stamp = random.choice(stamps)
            if cid and stamp.get('characterId1') != cid and stamp.get('characterId2') != cid:
                continue
            if can_make and not await ensure_stamp_maker_base_image(ctx, stamp['id'], use_cutout=False):
                continue
            return stamp['id']
        return None

    # 如果存在角色昵称，只返回指定角色昵称的随机表情
    cid = None
    if args:
        for item in get_character_nickname_data():
            for nickname in item.nicknames:
                if args.startswith(nickname):
                    cid = item.id
                    args = args[len(nickname):].strip()
                    break

    if args:
        # 表情制作模式
        sid = await get_rand_sid(cid, True)
        assert_and_reply(sid, f"没有符合条件的表情")
        return await ctx.asend_reply_msg(await make_stamp_image_cq(ctx, sid, args, format))
    else:
        sid = await get_rand_sid(cid, False)
        assert_and_reply(sid, f"没有符合条件的表情")
        return await ctx.asend_reply_msg(await get_stamp_image_cq(ctx, sid, format))
    

# 刷新表情底图
pjsk_stamp_refresh = SekaiCmdHandler([
    "/pjsk stamp refresh", "/pjsk表情刷新", "/pjsk刷新表情",
    "/pjsk刷新表情底图", "/pjsk表情刷新底图",
])
pjsk_stamp_refresh.check_cdrate(cd).check_wblist(gbl)
@pjsk_stamp_refresh.handle()
async def _(ctx: SekaiHandlerContext):
    await ctx.block_region()
    args = ctx.get_args().strip()
    try:
        sid = int(args)
        assert sid >= 0
    except:
        return await ctx.asend_reply_msg(f"使用方式: {ctx.original_trigger_cmd} 123")

    filename = f"{sid:06d}.png"
    base_image_path = f"{STAMP_BASE_IMAGE_DIR}/{filename}"
    cutout_image_path = f"{STAMP_CUTOUT_IMAGE_DIR}/{filename}"
    assert_and_reply(not os.path.isfile(base_image_path), f"表情{sid}人工抠图底图已存在")
    if os.path.isfile(cutout_image_path):
        os.remove(cutout_image_path)

    path, _ = await ensure_stamp_maker_base_image(ctx, sid, use_cutout=True)
    with TempFilePath("gif") as gif_path:
        save_transparent_static_gif(open_image(path), gif_path)
        img_cq = await get_image_cq(gif_path)
    return await ctx.asend_reply_msg(f"表情{sid}底图已刷新\n{img_cq}")


# 查看表情底图
pjsk_stamp_base = SekaiCmdHandler([
    "/pjsk stamp base", "/pjsk表情底图",
])
pjsk_stamp_base.check_cdrate(cd).check_wblist(gbl)
@pjsk_stamp_base.handle()
async def _(ctx: SekaiHandlerContext):
    args = ctx.get_args().strip()
    gif = True
    if "png" in args:
        gif = False
        args = args.replace("png", "").strip()
    try:
        sid = int(args)
        assert sid >= 0
    except:
        return await ctx.asend_reply_msg(f"使用方式: {ctx.original_trigger_cmd} 123")

    path, _ = await ensure_stamp_maker_base_image(ctx, sid, use_cutout=False)
    assert_and_reply(path, f"该表情还没有底图，使用\"/pjsk表情刷新{sid}\"生成底图")

    if gif:
        with TempFilePath("gif") as gif_path:
            save_transparent_static_gif(open_image(path), gif_path)
            img_cq = await get_image_cq(gif_path)
    else:
        img_cq = await get_image_cq(path)

    return await ctx.asend_reply_msg(img_cq + f"使用\"/pjsk表情刷新{sid}\"可重新生成底图")

