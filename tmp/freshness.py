import json, glob, os
files = glob.glob('data/m60_cache/*.json')
print('m60 文件数:', len(files))
d = json.load(open('data/m60_cache/600519.json'))
print('600519 m60 bar数:', len(d), '最后bar:', d[-1])
# hithink 日更新鲜度
h = sorted(glob.glob('data/hithink/*.json'))[-5:]
print('hithink 最新文件:', [os.path.basename(x) for x in h])
# cb_m5 攒数
cb = sorted(glob.glob('data/cb_m5/*'))[-5:]
print('cb_m5 最新:', [os.path.basename(x) for x in cb])
# 新闻归档
na = 'data/news_archive.jsonl'
if os.path.exists(na):
    lines = open(na).readlines()
    print('news_archive 行数:', len(lines), '最后行日期:', json.loads(lines[-1]).get('date', json.loads(lines[-1]).get('pub_time', '?')) if lines else None)
