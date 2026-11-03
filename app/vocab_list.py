"""Curated beginner vocabulary for the kana courses.

Only the spelling, a category and an English *lookup keyword* are written here.
Meanings, part of speech, kanji spellings and example sentences are pulled from
JMdict / Tatoeba by scripts/build_content.py, which fails loudly when a word
cannot be matched — so no translations are invented by hand.
"""

HIRAGANA_WORDS = [
    # food
    ("すし", "sushi", "food"), ("りんご", "apple", "food"), ("みかん", "mandarin", "food"), ("さかな", "fish", "food"),
    ("にく", "meat", "food"), ("たまご", "egg", "food"), ("ごはん", "rice", "food"), ("みず", "water", "food"),
    ("おちゃ", "tea", "food"), ("やさい", "vegetable", "food"), ("うどん", "udon", "food"), ("そば", "soba", "food"),
    ("もち", "mochi", "food"), ("なし", "pear", "food"),
    # animals
    ("いぬ", "dog", "animals"), ("ねこ", "cat", "animals"), ("とり", "bird", "animals"), ("うま", "horse", "animals"),
    ("うし", "cattle", "animals"), ("さる", "monkey", "animals"), ("くま", "bear", "animals"), ("うさぎ", "rabbit", "animals"),
    ("きつね", "fox", "animals"), ("かめ", "turtle", "animals"), ("かえる", "frog", "animals"), ("へび", "snake", "animals"),
    ("ぶた", "pig", "animals"), ("ひつじ", "sheep", "animals"), ("ねずみ", "mouse", "animals"),
    # daily life
    ("いえ", "house", "daily life"), ("へや", "room", "daily life"), ("つくえ", "desk", "daily life"), ("いす", "chair", "daily life"),
    ("かばん", "bag", "daily life"), ("かさ", "umbrella", "daily life"), ("とけい", "clock", "daily life"), ("まど", "window", "daily life"),
    ("ほん", "book", "daily life"), ("かぎ", "key", "daily life"),
    # nature
    ("やま", "mountain", "nature"), ("かわ", "river", "nature"), ("うみ", "sea", "nature"), ("そら", "sky", "nature"),
    ("あめ", "rain", "nature"), ("ゆき", "snow", "nature"), ("はな", "flower", "nature"), ("き", "tree", "nature"),
    ("いし", "stone", "nature"), ("もり", "forest", "nature"), ("かぜ", "wind", "nature"), ("ほし", "star", "nature"),
    ("つき", "moon", "nature"), ("くも", "cloud", "nature"),
    # people
    ("ひと", "person", "people"), ("ともだち", "friend", "people"), ("せんせい", "teacher", "people"), ("こども", "child", "people"),
    ("はは", "mother", "people"), ("ちち", "father", "people"), ("あに", "older brother", "people"), ("あね", "older sister", "people"),
    ("おとこ", "man", "people"), ("おんな", "woman", "people"), ("かぞく", "family", "people"),
    # time
    ("あさ", "morning", "time"), ("ひる", "noon", "time"), ("よる", "night", "time"), ("きょう", "today", "time"),
    ("あした", "tomorrow", "time"), ("きのう", "yesterday", "time"), ("いま", "now", "time"), ("まいにち", "every day", "time"),
    ("らいねん", "next year", "time"),
    # transport
    ("くるま", "car", "transport"), ("でんしゃ", "train", "transport"), ("ふね", "ship", "transport"), ("じてんしゃ", "bicycle", "transport"),
    ("ひこうき", "aeroplane", "transport"), ("みち", "road", "transport"),
    # travel
    ("えき", "station", "travel"), ("たび", "travel", "travel"), ("ちず", "map", "travel"), ("ちかてつ", "subway", "travel"),
    ("くうこう", "airport", "travel"), ("おみやげ", "souvenir", "travel"),
    # hobbies
    ("うた", "song", "hobbies"), ("え", "picture", "hobbies"), ("しゃしん", "photograph", "hobbies"), ("つり", "fishing", "hobbies"),
    ("すいえい", "swimming", "hobbies"), ("えいが", "movie", "hobbies"),
    # clothing
    ("くつ", "shoes", "clothing"), ("ふく", "clothes", "clothing"), ("ぼうし", "hat", "clothing"), ("くつした", "socks", "clothing"),
    ("きもの", "kimono", "clothing"), ("ゆかた", "yukata", "clothing"),
    # countries
    ("にほん", "Japan", "countries"), ("ちゅうごく", "China", "countries"), ("かんこく", "Korea", "countries"),
    # technology
    ("でんわ", "telephone", "technology"), ("でんき", "electricity", "technology"), ("けいたい", "mobile phone", "technology"),
]

KATAKANA_WORDS = [
    # food
    ("コーヒー", "coffee", "food"), ("パン", "bread", "food"), ("ケーキ", "cake", "food"), ("ジュース", "juice", "food"),
    ("アイスクリーム", "ice cream", "food"), ("チーズ", "cheese", "food"), ("バナナ", "banana", "food"), ("トマト", "tomato", "food"),
    ("ラーメン", "ramen", "food"), ("カレー", "curry", "food"), ("ピザ", "pizza", "food"), ("サラダ", "salad", "food"),
    ("ミルク", "milk", "food"), ("チョコレート", "chocolate", "food"),
    # animals
    ("ライオン", "lion", "animals"), ("パンダ", "panda", "animals"), ("ゴリラ", "gorilla", "animals"), ("ペンギン", "penguin", "animals"),
    ("コアラ", "koala", "animals"), ("カンガルー", "kangaroo", "animals"), ("イルカ", "dolphin", "animals"),
    # daily life
    ("テーブル", "table", "daily life"), ("ベッド", "bed", "daily life"), ("ドア", "door", "daily life"), ("シャワー", "shower", "daily life"),
    ("トイレ", "toilet", "daily life"), ("タオル", "towel", "daily life"), ("ペン", "pen", "daily life"), ("ノート", "notebook", "daily life"),
    ("ティッシュ", "tissue", "daily life"), ("フォーク", "fork", "daily life"),
    # technology
    ("コンピューター", "computer", "technology"), ("パソコン", "personal computer", "technology"), ("テレビ", "television", "technology"),
    ("ラジオ", "radio", "technology"), ("インターネット", "internet", "technology"), ("メール", "email", "technology"),
    ("スマホ", "smartphone", "technology"), ("アプリ", "app", "technology"), ("カメラ", "camera", "technology"), ("データ", "data", "technology"),
    ("ファイル", "file", "technology"), ("ソフトウェア", "software", "technology"), ("ウェブ", "web", "technology"),
    # countries
    ("アメリカ", "America", "countries"), ("イギリス", "United Kingdom", "countries"), ("フランス", "France", "countries"),
    ("ドイツ", "Germany", "countries"), ("イタリア", "Italy", "countries"), ("スペイン", "Spain", "countries"), ("カナダ", "Canada", "countries"),
    ("ブラジル", "Brazil", "countries"), ("インド", "India", "countries"), ("ロシア", "Russia", "countries"),
    ("オーストラリア", "Australia", "countries"), ("メキシコ", "Mexico", "countries"),
    # transport
    ("バス", "bus", "transport"), ("タクシー", "taxi", "transport"), ("トラック", "truck", "transport"), ("バイク", "motorcycle", "transport"),
    ("ヘリコプター", "helicopter", "transport"),
    # travel
    ("ホテル", "hotel", "travel"), ("パスポート", "passport", "travel"), ("チケット", "ticket", "travel"), ("スーツケース", "suitcase", "travel"),
    ("ツアー", "tour", "travel"), ("レストラン", "restaurant", "travel"),
    # hobbies
    ("サッカー", "soccer", "hobbies"), ("テニス", "tennis", "hobbies"), ("ギター", "guitar", "hobbies"), ("ピアノ", "piano", "hobbies"),
    ("ダンス", "danc", "hobbies"), ("スキー", "ski", "hobbies"), ("アニメ", "anim", "hobbies"), ("ゴルフ", "golf", "hobbies"),
    ("パーティー", "party", "hobbies"),
    # clothing
    ("シャツ", "shirt", "clothing"), ("スカート", "skirt", "clothing"), ("コート", "coat", "clothing"), ("ネクタイ", "necktie", "clothing"),
    ("ジーンズ", "jeans", "clothing"), ("セーター", "sweater", "clothing"), ("ドレス", "dress", "clothing"),
    # people
    ("チーム", "team", "people"), ("シェフ", "chef", "people"),
]
