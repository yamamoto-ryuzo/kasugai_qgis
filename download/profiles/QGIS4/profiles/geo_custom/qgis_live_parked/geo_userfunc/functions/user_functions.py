from qgis.core import *
from qgis.gui import *


def openProject():
    pass


def saveProject():
    pass


def closeProject():
    pass


@qgsfunction(args='auto', group='ユーザー関数')
def zen2han(moji, feature, parent):

    # 全角の文字列
    FULLWIDTH_DIGITS = "０１２３４５６７８９"
    FULLWIDTH_ALPHABET = "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    FULLWIDTH_PUNCTUATION = "！＂＃＄％＆＇（）＊＋，－．／：；＜＝＞？＠［＼］＾＿｀｛｜｝～　"
    FULLWIDTH_ALPHANUMERIC = FULLWIDTH_DIGITS + FULLWIDTH_ALPHABET  # 英数字
    FULLWIDTH_ALL = FULLWIDTH_ALPHANUMERIC + FULLWIDTH_PUNCTUATION  # 英数字、記号

    # 半角の文字列
    HALFWIDTH_DIGITS = "0123456789"
    HALFWIDTH_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    HALFWIDTH_PUNCTUATION = "!\"#$%&'()*+,-./:;<=>?@[\]^_`{|}~ "
    HALFWIDTH_ALPHANUMERIC = HALFWIDTH_DIGITS + HALFWIDTH_ALPHABET  # 英数字
    HALFWIDTH_ALL = HALFWIDTH_ALPHANUMERIC + HALFWIDTH_PUNCTUATION  # 英数字、記号

    # 数字、アルファベットを半角に変換する。
    conv_map = str.maketrans(FULLWIDTH_ALPHANUMERIC, HALFWIDTH_ALPHANUMERIC)

    moji = moji.translate(conv_map)
    return moji


def han2zen(moji, feature, parent):

    # 全角の文字列
    FULLWIDTH_DIGITS = "０１２３４５６７８９"
    FULLWIDTH_ALPHABET = "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    FULLWIDTH_PUNCTUATION = "！＂＃＄％＆＇（）＊＋，－．／：；＜＝＞？＠［＼］＾＿｀｛｜｝～　"
    FULLWIDTH_ALPHANUMERIC = FULLWIDTH_DIGITS + FULLWIDTH_ALPHABET  # 英数字
    FULLWIDTH_ALL = FULLWIDTH_ALPHANUMERIC + FULLWIDTH_PUNCTUATION  # 英数字、記号

    # 半角の文字列
    HALFWIDTH_DIGITS = "0123456789"
    HALFWIDTH_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    HALFWIDTH_PUNCTUATION = "!\"#$%&'()*+,-./:;<=>?@[\]^_`{|}~ "
    HALFWIDTH_ALPHANUMERIC = HALFWIDTH_DIGITS + HALFWIDTH_ALPHABET  # 英数字
    HALFWIDTH_ALL = HALFWIDTH_ALPHANUMERIC + HALFWIDTH_PUNCTUATION  # 英数字、記号

    # 数字、アルファベットを全角に変換する。
    conv_map = str.maketrans(HALFWIDTH_ALPHANUMERIC, FULLWIDTH_ALPHANUMERIC)

    moji = moji.translate(conv_map)
    return moji
