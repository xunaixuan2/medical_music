"""课程内容（MVP 阶段：内置单门课程，后续由内容后台 / 数据库承接）。"""

_SENTENCES = [
    {"hanzi": "春三月，此为发陈。", "pinyin": "chūn sān yuè，cǐ wéi fā chén。"},
    {"hanzi": "天地俱生，万物以荣，", "pinyin": "tiān dì jù shēng，wàn wù yǐ róng，"},
    {"hanzi": "夜卧早起，广步于庭，", "pinyin": "yè wò zǎo qǐ，guǎng bù yú tíng，"},
    {"hanzi": "被发缓形，以使志生，", "pinyin": "pī fà huǎn xíng，yǐ shǐ zhì shēng，"},
    {"hanzi": "此春气之应，养生之道也；", "pinyin": "cǐ chūn qì zhī yìng，yǎng shēng zhī dào yě；"},
    {"hanzi": "夏三月，此谓蕃秀。", "pinyin": "xià sān yuè，cǐ wèi fán xiù。"},
    {"hanzi": "天地气交，万物华实，", "pinyin": "tiān dì qì jiāo，wàn wù huá shí，"},
    {"hanzi": "夜卧早起，无厌于日，", "pinyin": "yè wò zǎo qǐ，wú yàn yú rì，"},
    {"hanzi": "使志无怒，使华英成秀，", "pinyin": "shǐ zhì wú nù，shǐ huá yīng chéng xiù，"},
    {"hanzi": "此夏气之应，养长之道也。", "pinyin": "cǐ xià qì zhī yìng，yǎng zhǎng zhī dào yě。"},
]

COURSES = {
    "siqi_tiaoshen_01": {
        "id": "siqi_tiaoshen_01",
        "title": "四气调神大论（选段）",
        "book": "《黄帝内经·素问》",
        "lyrics": "".join(s["hanzi"] for s in _SENTENCES),
        "expected_duration_ms": 60000,
        "sentences": _SENTENCES,
    },
}


def get_course(course_id: str) -> dict | None:
    return COURSES.get(course_id)
