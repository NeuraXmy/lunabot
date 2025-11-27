from ..utils import *


# ======================= 基础路径 ======================= #

SEKAI_DATA_DIR = "data/sekai"
SEKAI_CONFIG_DIR = "config/sekai"
SEKAI_ASSET_DIR = f"{SEKAI_DATA_DIR}/assets"


# ======================= 基础设施 ======================= #

config = Config('sekai.sekai')
logger = get_logger("Sekai")
file_db = get_file_db(f"{SEKAI_DATA_DIR}/db.json", logger)

cd = ColdDown(file_db, logger)
gbl = get_group_black_list(file_db, logger, 'sekai')


# ======================= 通用常量 ======================= #

@dataclass
class CharacterNicknameData:
    id: int
    nicknames: List[str]
    first_nickname: str

_nickname_data: List[CharacterNicknameData] = []
_nickname_data_mtime = None

ALL_SERVER_REGIONS = ['jp', 'en', 'tw', 'kr', 'cn']
ALL_SERVER_REGION_NAMES = ['日服', '国际服', '台服', '韩服', '国服']
NEED_TRANSLATE_REGIONS = ['jp', 'en', 'kr']
TRANSLATED_REGIONS = ['cn', 'tw']

REGION_UTC_OFFSET = {
    'jp': 9,
    'en': -7,
    'cn': 8,
    'tw': 8,
    'kr': 9,
}

UNITS = [
    "light_sound",
    "idol",
    "street",
    "theme_park",
    "school_refusal",
    "piapro",
]
UNIT_LN = "light_sound"
UNIT_MMJ = "idol"
UNIT_VBS = "street"
UNIT_WS = "theme_park"
UNIT_25 = "school_refusal"
UNIT_VS = "piapro"
UNIT_NAMES = [
    ('light_sound', 'ln'),
    ('idol', 'mmj'),
    ('street', 'vbs'),
    ('theme_park', 'ws'),
    ('school_refusal', '25h', '25时', '25'),
    ('piapro', 'vs', 'v'),
]
UNIT_ABBRS = {
    "light_sound": "ln",
    "idol": "mmj",
    "street": "vbs",
    "theme_park": "ws",
    "school_refusal": "25h",
    "piapro": "vs",
}
CID_UNIT_MAP = {
    1: "light_sound", 2: "light_sound", 3: "light_sound", 4: "light_sound", 
    5: "idol", 6: "idol", 7: "idol", 8: "idol",
    9: "street", 10: "street", 11: "street", 12: "street",
    13: "theme_park", 14: "theme_park", 15: "theme_park", 16: "theme_park",
    17: "school_refusal", 18: "school_refusal", 19: "school_refusal", 20: "school_refusal",
    21: "piapro", 22: "piapro", 23: "piapro", 24: "piapro", 25: "piapro", 26: "piapro",
}
UNIT_CID_MAP = {
    "light_sound": [1, 2, 3, 4],
    "idol": [5, 6, 7, 8],
    "street": [9, 10, 11, 12],
    "theme_park": [13, 14, 15, 16],
    "school_refusal": [17, 18, 19, 20],
    'piapro': [21, 22, 23, 24, 25, 26],
}
UNIT_COLORS = [
    (68,85,221,255),
    (136,221,68,255),
    (238,17,102,255),
    (255,153,0,255),
    (136,68,153,255),
]

CARD_ATTRS = [
    "cool",
    "happy",
    "mysterious",
    "cute",
    "pure",
]
CARD_ATTR_ABBR = {
    "cool": "蓝",
    "happy": "橙",
    "mysterious": "紫",
    "cute": "粉",
    "pure": "绿",
}
CARD_ATTR_NAMES = [
    ("cool", "COOL", "Cool", "帅气", "蓝星", "蓝"),
    ("happy", "HAPPY", "Happy", "快乐", "橙心", "橙", '黄'),
    ("mysterious", "MYSTERIOUS", "Mysterious", "神秘", "紫月", "紫"),
    ("cute", "CUTE", "Cute", "可爱", "粉花", "粉"),
    ("pure", "PURE", "Pure", "纯洁", "绿草", "绿"),
]
CARD_RARE_NAMES = [
    ("rarity_1", "1星", "一星", "1x", "1"),
    ("rarity_2", "2星", "二星", "两星", "2x", "2"),
    ("rarity_3", "3星", "三星", "3x", "3"),
    ("rarity_4", "4星", "四星", "4x", "4"),
    ("rarity_birthday", "生日", "生日卡", "bd"),
]
CARD_SUPPLIES_NAMES = [
    ("bloom_festival_limited", "新fes", "新fes限", "新fes限定", "新Fes", "新Fes限定",
     "bfes", "bfes限", "bfes限定", "bf",),
    ("unit_event_limited", "wl", "wl限", "wl限定", "worldlink", "worldlink限定", "WL"),
    ("collaboration_limited", "联动", "联动限定"),
    ("colorful_festival_limited", 'cfes', 'cfes限定', "fes", "fes限", "fes限定", "Fes", "Fes限定"),
    ("not_limited", "非限", "非限定", '常驻',),
    ("term_limited", "期间限定", "期间"),
    ("all_limited", "限定", "限"),
]
CARD_SUPPLIES_SHOW_NAMES = {
    "term_limited": "期间限定",
    "colorful_festival_limited": "Fes限定",
    "bloom_festival_limited": "BFes限定",
    "unit_event_limited": "WL限定",
    "collaboration_limited": "联动限定",
}
CARD_SKILL_NAMES = [
    ("life_recovery", "奶", "奶卡"),
    ("score_up", "分", "分卡"),
    ("judgment_up", "判", "判卡"),
]

try:
    UNKNOWN_IMG = Image.open(f"{SEKAI_ASSET_DIR}/static_images/unknown.png")
except Exception as e:
    logger.warning(f"加载 UNKNOWN_IMG 失败: {get_exc_desc(e)}")
    UNKNOWN_IMG = None


MUSIC_TAG_UNIT_MAP = {
    'light_music_club': 'light_sound',
    'street': 'street',
    'idol': 'idol',
    'theme_park': 'theme_park',
    'school_refusal': 'school_refusal',
    'vocaloid': 'piapro',
    'other': None,
}

# ======================= 通用功能 ======================= #

# 将指定区服上的小时转换为本地小时 （例如日服烤森刷新5点, 转换为本地则返回4点）
def region_hour_to_local(region: str, hour: int) -> int:
    return hour + REGION_UTC_OFFSET['cn'] - REGION_UTC_OFFSET[region]

# 将指定区服上的时间转换为本地时间 （例如日服烤森刷新5点, 转换为本地则返回4点）
def region_dt_to_local(region: str, dt: datetime) -> datetime:
    return dt + timedelta(hours=REGION_UTC_OFFSET['cn']) - timedelta(hours=REGION_UTC_OFFSET[region])

# 区服是否已经五周年更新
def is_fifth_anniversary(region: str) -> bool:
    return region in config.get('fifth_anniv_regions')

# 获取角色生日
def get_character_birthday(cid: int) -> Tuple[int, int]:
    return Config('sekai.character_birthday').get('birthdays')[cid]

# 获取角色下次生日时间点
def get_character_next_birthday_dt(region: str, cid: int, dt: datetime = None) -> datetime:
    dt = dt or datetime.now()
    m, d = get_character_birthday(cid)
    next_birthday = dt.replace(month=m, day=d, hour=0, minute=0, second=0, microsecond=0)
    if next_birthday < dt:
        next_birthday = next_birthday.replace(year=next_birthday.year + 1)
    return region_dt_to_local(region, next_birthday)

# 获取角色昵称数据
def get_character_nickname_data() -> List[CharacterNicknameData]:
    global _nickname_data, _nickname_data_mtime
    cfg = Config('sekai.character_nicknames')
    mtime = cfg.mtime()
    if mtime != _nickname_data_mtime:
        _nickname_data = [
            CharacterNicknameData(
                id = item['id'],
                nicknames=sorted(item['nicknames'], key=len, reverse=True),
                first_nickname=item['nicknames'][0],
            ) for item in cfg.get('nicknames')
        ]
        _nickname_data_mtime = mtime
    return _nickname_data

# 获取角色首个昵称，如果不存在则返回None
def get_character_first_nickname(cid: int) -> Optional[str]:
    data = get_character_nickname_data()
    for item in data:
        if item.id == cid:
            return item.first_nickname
    return None

# 通过区服名获取区服ID
def get_region_name(region: str):
    return ALL_SERVER_REGION_NAMES[ALL_SERVER_REGIONS.index(region)]

# 通过角色ID获取角色昵称，不存在则返回空列表
def get_nicknames_by_chara_id(cid: int) -> List[str]:
    """
    通过角色ID获取角色昵称，不存在则返回空列表
    """
    for item in get_character_nickname_data():
        if item.id == cid:
            return item.nicknames
    return []

# 通过角色昵称获取角色ID，不存在则返回None
def get_cid_by_nickname(nickname: str) -> Optional[int]:
    """
    通过角色昵称获取角色ID，不存在则返回None
    """
    if nickname is None:
        return None
    for item in get_character_nickname_data():
        if nickname in item.nicknames:
            return item.id
    return None

# 从参数中提取角色昵称，返回角色ID和剩余参数
def extract_nickname_from_args(args: str, default=None) -> Tuple[Optional[str], str]:
    best_match: str | None = default # 最匹配的一项，也就是匹配的长度最长的一项
    max_length: int = 0 # 最匹配的一项的长度
    for item in get_character_nickname_data():
        for nickname in item.nicknames:
            if nickname in args:
                current_length = len(nickname)
                if current_length > max_length:
                    best_match = nickname
    if best_match is not None:
        args = args.replace(best_match, "").strip()
    return best_match, args

# 获取所有(昵称, 角色ID)对
def get_all_nickname_cid_pairs() -> List[Tuple[str, int]]:
    """
    获取所有(昵称, 角色ID)对
    """
    all_nicknames = []
    for item in get_character_nickname_data():
        for nickname in item.nicknames:
            all_nicknames.append((nickname, item.id))
    all_nicknames.sort(key=lambda x: len(x[0]), reverse=True)
    return all_nicknames

# 从角色id获取角色团名
def get_unit_by_chara_id(cid: int) -> str:
    return CID_UNIT_MAP.get(cid, None)

# 从角色昵称获取角色团名
def get_unit_by_nickname(nickname: str) -> str:
    return get_unit_by_chara_id(get_cid_by_nickname(nickname))


# 从文本提取年份 返回(年份, 文本)
def extract_year(text: str, default=None) -> Tuple[int, str]:
    now_year = datetime.now().year
    if "明年" in text:
        return now_year + 1, text.replace("明年", "").strip()
    if "今年" in text:
        return now_year, text.replace("今年", "").strip()
    if "去年" in text:
        return now_year - 1, text.replace("去年", "").strip()
    if "前年" in text:
        return now_year - 2, text.replace("前年", "").strip()
    for year in range(now_year, 2020, -1):
        str_year = str(year)
        for s in (str_year + "年", str_year[-2:] + "年"):
            if s in text:
                return year, text.replace(s, "").strip()
    return default, text

# 从文本提取团名 返回(团名, 文本)
def extract_unit(text: str, default=None) -> Tuple[str, str]:
    all_names = []
    for names in UNIT_NAMES:
        for name in names:
            all_names.append((names[0], name))
    all_names.sort(key=lambda x: len(x[1]), reverse=True)
    for first_name, name in all_names:
        if name in text:
            return first_name, text.replace(name, "").strip()
    return default, text

# 从文本提取vs团名 返回(团名, 文本)
def extract_vs_unit(text: str, default=None) -> Tuple[str, str]:
    all_names = []
    for names in UNIT_NAMES:
        for name in names:
            all_names.append((names[0], name + "vs"))
            all_names.append((names[0], name + "v"))
    all_names.sort(key=lambda x: len(x[1]), reverse=True)
    for first_name, name in all_names:
        if name in text:
            return first_name, text.replace(name, "").strip()
    return default, text

# 从文本提取oc团名 返回(团名, 文本)
def extract_oc_unit(text: str, default=None) -> Tuple[str, str]:
    all_names = []
    for names in UNIT_NAMES:
        for name in names:
            all_names.append((names[0], name + "oc"))
            all_names.append((names[0], "纯" + name))
    all_names.sort(key=lambda x: len(x[1]), reverse=True)
    for first_name, name in all_names:
        if name in text:
            return first_name, text.replace(name, "").strip()
    return default, text

# 从文本提取卡牌属性 返回(属性名, 文本)
def extract_card_attr(text: str, default=None) -> Tuple[str, str]:
    all_names = []
    for names in CARD_ATTR_NAMES:
        for name in names:
            all_names.append((names[0], name))
    all_names.sort(key=lambda x: len(x[1]), reverse=True)
    for first_name, name in all_names:
        if name in text:
            return first_name, text.replace(name, "").strip()
    return default, text

# 从文本提取卡牌稀有度 返回(稀有度名, 文本)
def extract_card_rare(text: str, default=None) -> Tuple[str, str]:
    all_names = []
    for names in CARD_RARE_NAMES:
        for name in names:
            all_names.append((names[0], name))
    all_names.sort(key=lambda x: len(x[1]), reverse=True)
    for first_name, name in all_names:
        if name in text:
            return first_name, text.replace(name, "").strip()
    return default, text

# 从文本提取卡牌供给类型 返回(供给类型名, 文本)
def extract_card_supply(text: str, default=None) -> Tuple[str, str]:
    all_names = []
    for names in CARD_SUPPLIES_NAMES:
        for name in names:
            all_names.append((names[0], name))
    all_names.sort(key=lambda x: len(x[1]), reverse=True)
    for first_name, name in all_names:
        if name in text:
            return first_name, text.replace(name, "").strip()
    return default, text

# 从文本提取卡牌技能类型 返回(技能类型名, 文本)
def extract_card_skill(text: str, default=None) -> Tuple[str, str]:
    all_names = []
    for names in CARD_SKILL_NAMES:
        for name in names:
            all_names.append((names[0], name))
    all_names.sort(key=lambda x: len(x[1]), reverse=True)
    for first_name, name in all_names:
        if name in text:
            return first_name, text.replace(name, "").strip()
    return default, text

