import sys
sys.path.insert(0, '/opt/data/python-libs')
sys.path.insert(0, 'engine')
import baostock as bs
import update_kcache as uk

lg = bs.login()
assert lg.error_code == '0', lg.error_msg
uk.update_index('2026-09-19')
bs.logout()
# 验证
import json
rows = json.load(open('data/index_sh000001.json'))
print('index 最新 3 行:', rows[-3:])
