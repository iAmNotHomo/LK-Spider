import asyncio, aiohttp
from lxml import html
import os, random, json, zhconv, re, execjs


SAVE_DIR = 'D:/books/'

# 下载任务写到这个列表里
BOOK_LIST = []
'''
BOOK_NODE = {
    'title': str, 不需要和轻国标题一致
    'sid': int,   合集参数; 单本则填写0, 不可以省略
    'aid': int    单本参数; 合集省略这一项
}

例: BOOK_LIST = [{'title':'青猪','sid':660},{'title':'末日二问-7','sid':0,'aid':968116}]
其中青猪是系列合集, url = https://www.lightnovel.us/cn/series/660
末日二问第七卷是单本, url = https://www.lightnovel.us/cn/detail/968116
'''

LOGIN_INFO = {
    'username': '974689443@qq.com',
    'password': 'D142857ing'
}

# 并发数量
MAX_THREAD = 8

# 遇到付费章节, if IS_PURCHASE and (价格 <= MAX_PURCHASE): 购买该章节
IS_PURCHASE = False # 是否购买付费章节
MAX_PURCHASE = 1 # 价格高于这个数, 就不买

# 章节字数小于这个数, 就不下载
LEAST_WORDS = 0

# 一次请求等这么久还没收到服务器回复, 就重发请求
TIME_OUT = 16 # 秒

# 试了这么多次还连不上服务器, 就放弃
RETRY_TIME = 3

# 防ban
SLEEP_TIME = 4 # 请求延迟时间 = random() * SLEEP_TIME, 秒


# 下面的都不用改

URL_CONFIG = {
    'lightnovel_login': 'https://www.lightnovel.us/proxy/api/user/login',
    'lightnovel_page': 'https://www.lightnovel.us/proxy/api/category/get-article-by-cate',
    'lightnovel_chapter': 'https://www.lightnovel.us/cn/detail/%d',
    'lightnovel_book': 'https://www.lightnovel.us/cn/series/%d',
    'lightnovel_pay': 'https://www.lightnovel.us/proxy/api/coin/use',
    'lightnovel_illustration': 'https://www.lightnovel.us%s',
}
XPATH_DICT = {
    'lightnovel_content': '//article[@id=\'article-main-contents\']//text()',
    'lightnovel_illustration': '//article[@id=\'article-main-contents\']//img/@src',
}
HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36'
}


async def get_series(read):
    read = read.replace('window.__NUXT__', 'ccccc')
    js = execjs.compile(read)
    return js.eval('ccccc')


def get_cost(str):
    return int(re.findall('\d+', str)[0])


def write_byte_data(path, byte):
    with open(path, 'wb') as f:
        f.write(byte)


def write_str_data(path, str):
    str = zhconv.convert(str, 'zh-hans')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(str)


async def write_miss_data(str):
    with open(SAVE_DIR + "missing.txt", 'a', encoding='utf-8') as f:
        f.write(str)


def get_split_str_list(start, end, str):
    return re.findall('(?<=%s).*?(?=%s)' % (start, end), str)


def format_text(str0):
    str1 = str0.replace('/', '-').replace('\\', '-').replace('<', '-')
    str1 = str1.replace('>', '-').replace('|', '-').replace('\"', '-')
    str1 = str1.replace('?', '-').replace('*', '-').replace(':', '-')
    str1 = str1.replace('\xa0','').replace('\n','').replace('\r', '')
    str1 = str1.replace('\t', '').replace('\u3000', '')
    str1 = str1.replace('&nbsp;','').replace('\u002F', '-')
    return str1


async def lightnovel_mkdir(book_path, book):
    if not os.path.exists(SAVE_DIR + 'lightnovel/'):
        os.makedirs(SAVE_DIR + 'lightnovel/')
    dir_list = os.listdir(SAVE_DIR + 'lightnovel/')
    if dir_list:
        rename_flag = False
        for dir in dir_list:
            if book['sid'] == 0:
                if '_' + str(book['aid']) + '_' in dir:
                    dir = SAVE_DIR + 'lightnovel/' + dir
                    os.rename(dir, book_path)
                    rename_flag = True
                    break
            else:
                if '_' + str(book['sid']) + '_' in dir:
                    dir = SAVE_DIR + 'lightnovel/' + dir
                    os.rename(dir, book_path)
                    rename_flag = True
                    break

        if not rename_flag:
            os.makedirs(book_path)
    else:
        os.makedirs(book_path)


async def http_get_text(session, url, token):
    # 请求头
    headers = HEADERS
    headers['Cookie'] = 'token={%22security_key%22:%22' + token + '%22}'
    for _ in range(RETRY_TIME):
        try:
            response = await session.get(url=url, headers=headers, timeout=TIME_OUT)
        except Exception as e:
            print('获取文字连接已断开，重试中... %s' % url)
            print(e)
            raise e
        else:
            text = await response.text()
            return text
    return None


async def http_get_pic(session, url, referer):
    headers = {
        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'Accept-Encoding': HEADERS['Accept-Encoding'],
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'User-Agent': HEADERS['User-Agent'],
        'Referer': referer
    }
    pic = ''
    try:
        response = await session.get(url=url, headers=headers, timeout=TIME_OUT)
        pic = await response.read()
    except Exception:
        print('获取图片连接已断开 %s' % url)
        # 写入日志
        await write_miss_data('获取图片%s失败' % url + '\n')
    return pic


async def save_pic_list(session, path, pic_list):
    if pic_list:
        for pic_url in pic_list:
            if not pic_url.startswith('http'):
                pic_url = URL_CONFIG['lightnovel_illustration'] % pic_url
            pic_name = pic_url.split('/')[-1].replace(':', '_').replace('*', '_')
            if '?' in pic_name:
                pic_name = pic_name.replace('?' + pic_url.split('?')[-1], '')
            pic_name = pic_name.replace('?', '_')
            if len(pic_name) > 100:
                pic_name = pic_name[0:100]
            pic_path = path + '_' + pic_name
            pic_res = await http_get_pic(session, pic_url, 'https://www.lightnovel.us/')
            if pic_res:
                write_byte_data(pic_path, pic_res)


async def http_post_pay(session, aid, cost, token):
    print('%d开始打钱：%d轻币' % (aid, cost))
    url = URL_CONFIG['lightnovel_pay']
    # 请求头
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Encoding': HEADERS['Accept-Encoding'],
        'Accept-Language': HEADERS['Accept-Language'],
        'User-Agent': HEADERS['User-Agent']
    }
    # 传参
    param_data = {
        'client': 'web',
        'd': {
            'goods_id': 1,
            'number': 1,
            'params': aid,
            'price': cost,
            'security_key': token,
            'total_price': cost
        },
        'gz': 0,
        'is_encrypted': 0,
        'platform': 'pc',
        'sign': ''
    }
    try:
        response = await session.post(url=url, headers=headers, json=param_data, timeout=TIME_OUT)
        if not response.status == 200:
            print('打钱失败！')
        print('打钱成功！')
    except Exception as e:
        print('打钱失败！')


async def get_lightnovel_single(session, book_path, book, token, is_purchase=IS_PURCHASE):
    # 处理下换行符等特殊符号
    book['title'] = format_text(book['title'])
    content_path = book_path + '/' + book['title'] + '.txt'
    if not os.path.exists(content_path):
        await asyncio.sleep(random.random() * SLEEP_TIME)
        content_url = URL_CONFIG['lightnovel_chapter'] % book['aid']
        print('开始获取章节：%s 地址：%s' % (book['title'], content_url))
        content_text = await http_get_text(session, content_url, token)
        # 轻币打钱
        if '以下内容需要解锁观看' in content_text:
            if is_purchase:
                content_body = html.fromstring(content_text)
                if content_body.xpath('//button[contains(@class,\'unlock\')]/text()'):
                    cost_text = content_body.xpath('//button[contains(@class,\'unlock\')]/text()')[0]
                    cost = get_cost(cost_text)
                    if cost < MAX_PURCHASE:
                        await http_post_pay(session, book['aid'], cost, token)
                        await get_lightnovel_single(session, book_path, book, token, False)
        if '您可能没有访问权限' in content_text:
            # 仅app就没办法了
            write_str_data(content_path, '仅app')
        else:
            content_body = html.fromstring(content_text)
            # 文字内容
            content_list = content_body.xpath(XPATH_DICT['lightnovel_content'])
            content = '\n'.join(content_list)
            # 插画
            pic_list = content_body.xpath(XPATH_DICT['lightnovel_illustration'])
            # 保存内容
            write_str_data(content_path, content)
            # 保存插画
            await save_pic_list(session, book_path + '/' + book['title'], pic_list)


async def get_chapter_list(chapter_script_text):
    chapter_list = []
    chapter_text = await get_series(chapter_script_text)
    chapter_text_list = chapter_text['data'][0]['series']['articles']
    for _chapter in chapter_text_list:
        chapter = {'title': _chapter['title'],
                  'url': URL_CONFIG['lightnovel_chapter'] % _chapter['aid'],
                  'aid': _chapter['aid']}
        chapter_list.append(chapter)
    return chapter_list


async def get_lightnovel_content(session, book_path, chapter_list, token):
    for chapter in chapter_list:
        # 处理下换行符等特殊符号
        chapter['title'] = format_text(str(chapter['title']))
        content_path = book_path + '/' + chapter['title'] + '.txt'
        if not os.path.exists(content_path):
            await asyncio.sleep(random.random() * SLEEP_TIME)
            print('开始获取章节：%s 地址：%s' % (chapter['title'], chapter['url']))
            content_text = await http_get_text(session, chapter['url'], token)
            # 轻币打钱
            if '以下内容需要解锁观看' in content_text:
                if IS_PURCHASE:
                    content_body = html.fromstring(content_text)
                    if not content_body.xpath('//button[contains(@class,\'unlock\')]/text()'):
                        continue
                    cost_text = content_body.xpath('//button[contains(@class,\'unlock\')]/text()')[0]
                    cost = get_cost(cost_text)
                    if cost < MAX_PURCHASE:
                        await http_post_pay(session, chapter['aid'], cost, token)
                        content_text = await http_get_text(session, chapter['url'], token)
            if '您可能没有访问权限' in content_text:
                # 仅app就没办法了
                write_str_data(content_path, '仅app')
            else:
                content_body = html.fromstring(content_text)
                # 文字内容
                content_list = content_body.xpath(XPATH_DICT['lightnovel_content'])
                content = '\n'.join(content_list)
                # 插画
                pic_list = content_body.xpath(XPATH_DICT['lightnovel_illustration'])
                # 保存内容
                write_str_data(content_path, content)
                # 保存插画
                await save_pic_list(session, book_path + '/' + chapter['title'], pic_list)


async def get_lightnovel_chapter(session, book_path, book, token):
    chapter_url = URL_CONFIG['lightnovel_book'] % book['sid']
    chapter_text = await http_get_text(session, chapter_url, token)
    chapter_body = html.fromstring(chapter_text)
    chapter_script_text = chapter_body.xpath('//script/text()')[0]
    # 正则获取章节地址和章节名
    chapter_list = await get_chapter_list(chapter_script_text)
    await get_lightnovel_content(session, book_path, chapter_list, token)


async def download_book(session, book, thread_count, token):
    async with thread_count:
        # 创建目录
        # 处理下换行符等特殊符号
        book_title = format_text(book['title'])
        # 轻国分合集、非合集，非合集相当于只有一章的合集
        if book['sid'] == 0:
            book_path = SAVE_DIR + 'lightnovel/' + book_title + '_' + str(book['aid']) + '_'
            # 轻国的标题会变，根据aid判断是否存在同一目录，存在则重命名
            await lightnovel_mkdir(book_path, book)
            # 非合集处理，直接跳转到目标页面
            await get_lightnovel_single(session, book_path, book, token)
        else:
            book_path = SAVE_DIR + 'lightnovel/' + book_title + '_' + str(book['sid']) + '_'
            # 轻国的标题会变，根据sid判断是否存在同一目录，存在则重命名
            await lightnovel_mkdir(book_path, book)
            # 合集处理，先从合集获取章节再获取内容
            await get_lightnovel_chapter(session, book_path, book, token)


async def download_all_books(session, token):
    if not BOOK_LIST:
        return
    thread_count = asyncio.Semaphore(MAX_THREAD)
    tasks = []
    for book in BOOK_LIST:
        tasks.append(download_book(session, book, thread_count, token))
    await asyncio.wait(tasks)


async def http_login(session):
    print('开始登录...')
    url = URL_CONFIG['lightnovel_login']
    param_data = {
        'client': 'web',
        'd': {
            'username': LOGIN_INFO['username'],
            'password': LOGIN_INFO['password'],
        },
        'gz': 0,
        'is_encrypted': 0,
        'platform': 'pc',
        'sign': ''
    }
    headers = HEADERS
    headers['Accept'] = 'application/json, text/plain, */*'
    headers['Accept-Language'] = 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7'
    headers['Origin'] = 'https://www.lightnovel.us'
    headers['Referer'] = 'https://www.lightnovel.us/cn/'
    for _ in range(RETRY_TIME):
        try:
            response = await session.post(url=url, headers=headers, json=param_data, timeout=TIME_OUT)
            if not response.status == 200:
                raise Exception('response status error.')
        except Exception as e:
            print('登录失败！')
            raise e
        else:
            text = await response.text()
            # 轻国手动设置cookie
            text = json.loads(text)
            lightnovel_token = text['data']['security_key']
            print('登录成功！')
            return(lightnovel_token)
    return(None)


async def main():
    jar = aiohttp.CookieJar(unsafe=True)
    conn = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=conn, trust_env=True, cookie_jar=jar) as session:
        token = await http_login(session)
        if token:
            await download_all_books(session, token)


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())