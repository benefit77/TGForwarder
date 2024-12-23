import os
import socks
import shutil
import random
import time
import httpx
import json
import re
import asyncio
import urllib.parse
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient,functions
from telethon.tl.types import MessageMediaPhoto, MessageEntityTextUrl
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.functions.channels import JoinChannelRequest

'''
代理参数说明:
# SOCKS5
proxy = (socks.SOCKS5,proxy_address,proxy_port,proxy_username,proxy_password)
# HTTP
proxy = (socks.HTTP,proxy_address,proxy_port,proxy_username,proxy_password))
# HTTP_PROXY
proxy=(socks.HTTP,http_proxy_list[1][2:],int(http_proxy_list[2]),proxy_username,proxy_password)
'''

if os.environ.get("HTTP_PROXY"):
    http_proxy_list = os.environ["HTTP_PROXY"].split(":")


class TGForwarder:
    def __init__(self, api_id, api_hash, string_session, channels_groups_monitor, forward_to_channel,
                 limit, replies_limit, kw, ban, only_send, nokwforwards, fdown, download_folder, proxy, checknum, linkvalidtor, replacements, channel_match, hyperlink_text, past_years):
        self.checkbox = {}
        self.checknum = checknum
        self.history = 'history.json'
        # 正则表达式匹配资源链接
        self.pattern = r"(?:链接：\s*)?((?!https?://t\.me)https?://[^\s'】\n]+(?=\n|$)|magnet:\?xt=urn:btih:[a-zA-Z0-9]+)"
        self.api_id = api_id
        self.api_hash = api_hash
        self.string_session = string_session
        self.channels_groups_monitor = channels_groups_monitor
        self.forward_to_channel = forward_to_channel
        self.limit = limit
        self.replies_limit = replies_limit
        self.kw = kw
        # 获取当前年份
        current_year = datetime.now().year
        # 过滤今年之前的影视资源
        if not past_years:
            years_list = [str(year) for year in range(1895, current_year)]
            self.ban = ban+years_list
        else:
            self.ban = ban
        self.hyperlink_text = hyperlink_text
        self.replacements = replacements
        self.channel_match = channel_match
        self.linkvalidtor = linkvalidtor
        self.only_send = only_send
        self.nokwforwards = nokwforwards
        self.fdown = fdown
        self.download_folder = download_folder
        if not proxy:
            self.client = TelegramClient(StringSession(string_session), api_id, api_hash)
        else:
            self.client = TelegramClient(StringSession(string_session), api_id, api_hash, proxy=proxy)
    def random_wait(self, min_ms, max_ms):
        min_sec = min_ms / 1000
        max_sec = max_ms / 1000
        wait_time = random.uniform(min_sec, max_sec)
        time.sleep(wait_time)
    def contains(self, s, kw):
        return any(k in s for k in kw)
    def nocontains(self, s, ban):
        return not any(k in s for k in ban)
    def replace_targets(self, message: str):
        """
        根据用户自定义的替换规则替换文本内容
        参数:
        message (str): 需要替换的原始文本
        replacements (dict): 替换规则字典，键为目标替换词，值为要被替换的词语列表
        """
        # 遍历替换规则
        if self.replacements:
            for target_word, source_words in self.replacements.items():
                # 确保source_words是列表
                if isinstance(source_words, str):
                    source_words = [source_words]
                # 遍历每个需要替换的词
                for word in source_words:
                    # 使用替换方法，而不是正则
                    message = message.replace(word, target_word)
        return message
    async def dispatch_channel(self, message, jumpLink=''):
        hit = False
        if self.channel_match:
            for target_channel, kw in self.channel_match.items():
                if self.contains(message.message, kw):
                    await self.send(message,target_channel, jumpLink)
                    hit = True
        if not hit:
            await self.send(message, self.forward_to_channel, jumpLink)
    async def send(self, message, target_chat_name, jumpLink=''):
        text = message.message
        if jumpLink and self.hyperlink_text:
            for t in self.hyperlink_text:
                text = text.replace(t, jumpLink)
        if self.fdown and message.media and isinstance(message.media, MessageMediaPhoto):
            media = await message.download_media(self.download_folder)
            await self.client.send_file(target_chat_name, media, caption=self.replace_targets(text))
        else:
            await self.client.send_message(target_chat_name, self.replace_targets(text))
    async def get_peer(self,client, channel_name):
        peer = None
        try:
            peer = await client.get_input_entity(channel_name)
        except Exception as e:
            print(f"Unexpected error: {e}")
        finally:
            return peer
    async def get_all_replies(self,chat_name, message):
        '''
        获取频道消息下的评论，有些视频/资源链接被放在评论中
        '''
        offset_id = 0
        all_replies = []
        peer = await self.get_peer(self.client, chat_name)
        if peer is None:
            return []
        while True:
            try:
                replies = await self.client(functions.messages.GetRepliesRequest(
                    peer=peer,
                    msg_id=message.id,
                    offset_id=offset_id,
                    offset_date=None,
                    add_offset=0,
                    limit=100,
                    max_id=0,
                    min_id=0,
                    hash=0
                ))
                all_replies.extend(replies.messages)
                if len(replies.messages) < 100:
                    break
                offset_id = replies.messages[-1].id
            except Exception as e:
                print(f"Unexpected error while fetching replies: {e.__class__.__name__} {e}")
                break
        return all_replies
    async def redirect_url(self, message):
        link = []
        if message.entities:
            for entity in message.entities:
                if isinstance(entity, MessageEntityTextUrl):
                    if 'https://telegra.ph' in entity.url:
                        continue
                    else:
                        url = urllib.parse.unquote(entity.url)
                        matches = re.findall(self.pattern, url)
                        if matches:
                            link = matches[0]
        return link
    async def forward_messages(self, chat_name, limit):
        global total
        links = self.checkbox['links']
        sizes = self.checkbox['sizes']
        try:
            if try_join:
                await self.client(JoinChannelRequest(chat_name))
            chat = await self.client.get_entity(chat_name)
            messages = self.client.iter_messages(chat, limit=limit, reverse=False)
            async for message in messages:
                jumpLink = await self.redirect_url(message)
                self.random_wait(200, 1000)
                forwards = message.forwards
                if message.media:
                    # 视频
                    if hasattr(message.document, 'mime_type') and self.contains(message.document.mime_type,'video') and self.nocontains(message.message, self.ban):
                        if forwards:
                            size = message.document.size
                            if size not in sizes:
                                await self.client.forward_messages(self.forward_to_channel, message)
                                sizes.append(size)
                                total += 1
                            else:
                                print(f'视频已经存在，size: {size}')
                    # 图文(匹配关键词)
                    elif self.contains(message.message, self.kw) and message.message and self.nocontains(message.message, self.ban):
                        matches = re.findall(self.pattern, message.message)
                        if matches or jumpLink:
                            link = jumpLink if jumpLink else matches[0]
                            if link not in links:
                                link_ok = True if not self.linkvalidtor else False
                                if self.linkvalidtor:
                                    result = await self.netdisklinkvalidator(matches)
                                    for r in result:
                                        if r[1]:
                                            link_ok = True
                                if forwards and not self.only_send and link_ok:
                                    await self.client.forward_messages(self.forward_to_channel, message)
                                    total += 1
                                    links.append(link)
                                elif link_ok:
                                    await self.dispatch_channel(message, jumpLink)
                                    total += 1
                                    links.append(link)
                            else:
                                print(f'链接已存在，link: {link}')
                    # 图文(不含关键词，默认nokwforwards=False)，资源被放到评论中
                    elif self.nokwforwards and message.message and self.nocontains(message.message, self.ban):
                        replies = await self.get_all_replies(chat_name,message)
                        replies = replies[-self.replies_limit:]
                        for r in replies:
                            # 评论中的视频
                            if hasattr(r.document, 'mime_type') and self.contains(r.document.mime_type,'video') and self.nocontains(r.message, self.ban):
                                size = r.document.size
                                if size not in sizes:
                                    await self.client.forward_messages(self.forward_to_channel, r)
                                    total += 1
                                    sizes.append(size)
                                else:
                                    print(f'视频已经存在，size: {size}')
                            # 评论中链接关键词
                            elif self.contains(r.message, self.kw) and r.message and self.nocontains(r.message, self.ban):
                                matches = re.findall(self.pattern, r.message)
                                if matches:
                                    link = matches[0]
                                    if link not in links:
                                        link_ok = True if not self.linkvalidtor else False
                                        if self.linkvalidtor:
                                            result = await self.netdisklinkvalidator(matches)
                                            for r in result:
                                                if r[1]:
                                                    link_ok = r[1]
                                        if forwards and not self.only_send and link_ok:
                                            await self.client.forward_messages(self.forward_to_channel, r)
                                            total += 1
                                            links.append(link)
                                        elif link_ok:
                                            await self.dispatch_channel(message)
                                            total += 1
                                            links.append(link)
                                    else:
                                        print(f'链接已存在，link: {link}')
                # 纯文本消息
                elif message.message:
                    if self.contains(message.message, self.kw) and self.nocontains(message.message, self.ban):
                        matches = re.findall(self.pattern, message.message)
                        if matches or jumpLink:
                            link = jumpLink if jumpLink else matches[0]
                            if link not in links:
                                link_ok = True if not self.linkvalidtor else False
                                if self.linkvalidtor:
                                    result = await self.netdisklinkvalidator(matches)
                                    for r in result:
                                        if r[1]:
                                            link_ok = True
                                if forwards and not self.only_send and link_ok:
                                    await self.client.forward_messages(self.forward_to_channel, message)
                                    total += 1
                                    links.append(link)
                                elif link_ok:
                                    await self.dispatch_channel(message, jumpLink)
                                    total += 1
                                    links.append(link)
                            else:
                                print(f'链接已存在，link: {link}')
            self.checkbox['links'] = links
            self.checkbox['sizes'] = sizes
            print(f"从 {chat_name} 转发资源到 {self.forward_to_channel} total: {total}")
        except Exception as e:
            print(f"从 {chat_name} 转发资源到 {self.forward_to_channel} 失败: {e}")
    async def checkhistory(self):
        '''
        检索历史消息用于过滤去重
        '''
        links = []
        sizes = []
        if os.path.exists(self.history):
            with open(self.history, 'r', encoding='utf-8') as f:
                self.checkbox = json.loads(f.read())
                links = self.checkbox.get('links')
                sizes = self.checkbox.get('sizes')
        else:
            self.checknum = 5000

        chat = await self.client.get_entity(self.forward_to_channel)
        messages = self.client.iter_messages(chat, limit=self.checknum)
        async for message in messages:
            # 视频类型对比大小
            if hasattr(message.document, 'mime_type'):
                sizes.append(message.document.size)
            # 匹配出链接
            if message.message:
                matches = re.findall(self.pattern, message.message)
                for match in matches:
                    links.append(match)
        self.checkbox['links'] = list(set(links))
        self.checkbox['sizes'] = list(set(sizes))
    async def check_aliyun(self,share_id):
        api_url = "https://api.aliyundrive.com/adrive/v3/share_link/get_share_by_anonymous"
        headers = {"Content-Type": "application/json"}
        data = json.dumps({"share_id": share_id})
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, headers=headers, data=data)
            response_json = response.json()
            if response_json.get('has_pwd'):
                return True
            if response_json.get('code') == 'NotFound.ShareLink':
                return False
            if not response_json.get('file_infos'):
                return False
            return True
    async def check_115(self,share_id):
        api_url = "https://webapi.115.com/share/snap"
        params = {"share_code": share_id, "receive_code": ""}
        async with httpx.AsyncClient() as client:
            response = await client.get(api_url, params=params)
            response_json = response.json()
            if response_json.get('state'):
                return True
            elif '请输入访问码' in response_json.get('error', ''):
                return True
            return False
    async def check_quark(self,share_id):
        api_url = "https://drive.quark.cn/1/clouddrive/share/sharepage/token"
        headers = {"Content-Type": "application/json"}
        data = json.dumps({"pwd_id": share_id, "passcode": ""})
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, headers=headers, data=data)
            response_json = response.json()
            if response_json.get('message') == "ok":
                token = response_json.get('data', {}).get('stoken')
                if not token:
                    return False
                detail_url = f"https://drive-h.quark.cn/1/clouddrive/share/sharepage/detail?pwd_id={share_id}&stoken={token}&_fetch_share=1"
                detail_response = await client.get(detail_url)
                detail_response_json = detail_response.json()
                if detail_response_json.get('data', {}).get('share', {}).get('status') == 1:
                    return True
                else:
                    return False
            elif response_json.get('message') == "需要提取码":
                return True
            return False
    def extract_share_id(self,url):
        if "aliyundrive.com" in url or "alipan.com" in url:
            pattern = r"https?://[^\s]+/s/([a-zA-Z0-9]+)"
        elif "pan.quark.cn" in url:
            pattern = r"https?://[^\s]+/s/([a-zA-Z0-9]+)"
        elif "115.com" in url or "anxia.com" in url:
            pattern = r"https?://[^\s]+/s/([a-zA-Z0-9]+)"
        elif url.startswith("magnet:"):
            return "magnet"  # 磁力链接特殊值
        else:
            return None
        match = re.search(pattern, url)
        if match:
            return match.group(1)
        return None
    async def check_url(self,url):
        share_id = self.extract_share_id(url)
        if not share_id:
            print(f"无法识别的链接或网盘服务: {url}")
            return url, False
        if "aliyundrive.com" in url or "alipan.com" in url:
            result = await self.check_aliyun(share_id)
            return url, result
        elif "pan.quark.cn" in url:
            result = await self.check_quark(share_id)
            return url, result
        elif "115.com" in url or "anxia.com" in url:
            result = await self.check_115(share_id)
            return url, result
        elif share_id == "magnet":
            return url, True  # 磁力链接直接返回True
    async def netdisklinkvalidator(self,urls):
        tasks = [self.check_url(url) for url in urls]
        results = await asyncio.gather(*tasks)
        for url, result in results:
            print(f"{url} - {'有效' if result else '无效'}")
        return results
    # 统计今日更新
    async def daily_forwarded_count(self,target_channel):
        # 设置中国时区偏移（UTC+8）
        china_offset = timedelta(hours=8)
        china_tz = timezone(china_offset)
        # 获取中国时区的今天凌晨
        now = datetime.now(china_tz)
        start_of_day_china = datetime.combine(now.date(), datetime.min.time())
        start_of_day_china = start_of_day_china.replace(tzinfo=china_tz)
        # 转换为 UTC 时间
        start_of_day_utc = start_of_day_china.astimezone(timezone.utc)
        # 获取今天第一条消息
        result = await self.client(GetHistoryRequest(
            peer=target_channel,
            limit=1,  # 只需要获取一条消息
            offset_date=start_of_day_utc,
            offset_id=0,
            add_offset=0,
            max_id=0,
            min_id=0,
            hash=0
        ))
        # 如果没有消息，返回0
        if not result.messages:
            return f'今日共更新【0】条资源'
        # 获取第一条消息的位置
        first_message_pos = result.offset_id_offset
        # 今日消息总数就是从第一条消息到最新消息的距离
        today_count = first_message_pos + 1
        msg = f'今日共更新【{today_count}】条资源'
        return msg
    async def del_channel_forward_count_msg(self):
        # 删除消息
        chat_forward_count_msg_id = self.checkbox.get("chat_forward_count_msg_id")

        forward_to_channel_message_id = chat_forward_count_msg_id.get(self.forward_to_channel) if chat_forward_count_msg_id else None
        if forward_to_channel_message_id:
            await self.client.delete_messages(self.forward_to_channel, [forward_to_channel_message_id])

        if self.channel_match:
            for target_channel, _ in self.channel_match.items():
                target_channel_msg_id = chat_forward_count_msg_id.get(target_channel)
                await self.client.delete_messages(target_channel, [target_channel_msg_id])
    async def send_daily_forwarded_count(self):
        await self.del_channel_forward_count_msg()

        chat_forward_count_msg_id = {}
        msg = await self.daily_forwarded_count(self.forward_to_channel)
        sent_message = await self.client.send_message(self.forward_to_channel, msg)

        chat_forward_count_msg_id[self.forward_to_channel] = sent_message.id
        if self.channel_match:
            for target_channel, _ in self.channel_match.items():
                m = await self.daily_forwarded_count(target_channel)
                sm = await self.client.send_message(target_channel, m)
                chat_forward_count_msg_id[target_channel] = sm.id
        self.checkbox["chat_forward_count_msg_id"] = chat_forward_count_msg_id
    async def main(self):
        await self.checkhistory()
        if not os.path.exists(self.download_folder):
            os.makedirs(self.download_folder)
        for chat_name in self.channels_groups_monitor:
            limit = self.limit
            if '|' in chat_name:
                limit = int(chat_name.split('|')[1])
                chat_name = chat_name.split('|')[0]
            global total
            total = 0
            await self.forward_messages(chat_name, limit)
        await self.send_daily_forwarded_count()
        await self.client.disconnect()
        if self.fdown:
            shutil.rmtree(self.download_folder)
        with open(self.history, 'w+', encoding='utf-8') as f:
            f.write(json.dumps(self.checkbox))
    def run(self):
        with self.client.start():
            self.client.loop.run_until_complete(self.main())


if __name__ == '__main__':
    channels_groups_monitor = ['hao115', 'yunpanshare', 'dianyingshare', 'alyp_4K_Movies', 'Aliyun_4K_Movies','Quark_Movies',
                               'XiangxiuNB', 'kuakeyun', 'ucpanpan', 'ydypzyfx', 'tianyi_pd2',
                               'guaguale115', 'ucquark', 'NewQuark|60', 'alyp_1','shareAliyun']
    forward_to_channel = 'cloudShareForw'
    # 监控最近消息数
    limit = 20
    # 监控消息中评论数，有些视频、资源链接被放到评论中
    replies_limit = 1
    kw = ['链接', '片名', '名称', '剧名','magnet','drive.uc.cn','caiyun.139.com','cloud.189.cn','pan.quark.cn','115.com','anxia.com','alipan.com','aliyundrive.com','夸克云盘','阿里云盘','磁力链接']
    ban = ['预告', '预感', 'https://t.me/', '盈利', '即可观看','书籍','电子书','图书','软件','安卓','Android','课程','作品','教程','全书','名著','mobi','epub','pdf','PDF','PPT','抽奖','完整版','文学','有声','txt','MP3','mp3','WAV','CD','音乐','专辑','资源','模板','书中','读物','入门','零基础','常识','干货','电商','小红书','抖音','资料','华为','短剧','纪录片','纪录','学习']
    # 消息中的超链接文字，如果存在超链接，会用url替换文字
    hyperlink_text = ["点击查看"]
    # 替换消息中关键字(tag/频道/群组)
    replacements = {
        forward_to_channel: ['ucquark','uckuake',"yunpanshare", "yunpangroup", "Quark_0", "Quark_Movies", "guaguale115","Aliyundrive_Share_Channel", "alyd_g", "shareAliyun", "aliyundriveShare", "hao115", "Mbox115","NewQuark", "Quark_Share_Group", "QuarkRobot", "memosfanfan_bot", "aliyun_share_bot", "AliYunPanBot"],
        "动漫": ["国漫", "日漫"],
        "连续剧": ["国剧", "韩剧", "泰剧", "日剧"]
    }
    # 匹配关键字转发到不同频道/群组，不分组设置channel_match={}即可
    # channel_match = {
    #     "tg115": ["115.com","anxia.com"],
    #     "tgali": ["www.alipan.com","aliyundrive.com"],
    #     "tguc": ["drive.uc.cn"],
    #     "tgquark": ["pan.quark.cn"],
    #     "tg139": ["caiyun.139.com"],
    #     "tg189": ["cloud.189.cn"],
    #     "tgmagnet": ["magnet"],
    #     "tgmusic": ["音乐","专辑","MP3","WAV","CD"]
    # }
    channel_match = {}
    # 尝试加入公共群组频道，无法过验证
    try_join = False
    # 消息中不含关键词图文，但有些资源被放到消息评论中，如果需要监控评论中资源，需要开启，否则建议关闭
    nokwforwards = False
    # 图文资源只主动发送，不转发，可以降低限制风险；不支持视频场景
    only_send = True
    # 当频道禁止转发时，是否下载图片发送消息
    fdown = True
    download_folder = 'downloads'
    api_id = 20127766
    api_hash = 'be53098a502fc5d65a572041b67b9eb2'
    string_session = '1BVtsOKoBu0Yb-dJzmuYTTI33vIqrCnv6kNm9kTpgdxrY7-7A3q6lEUxZEOxrJQC7tCBAFCK4A4d6mG1PFoHrJnQSNRBdVQtWC73sTSn-CxlbHQXHm8bqsrlWdnFS4R57anXu81gx_WD-yWKfy6kBCo5unraUOcFjjUNsJ_aDJtqv_AjNCO25qeb4DicM2LBHzenMhNScyuKfZb4k21BLTMALmYHCphrN1-GOdLx_L8Z3CK0rCypFcXxY1MpYGJAcSvRJlEkss9aM966gb0cZYHWPHOWo8Qlmj8CJqMozWQnpAEwFRAx5ZL8OoF5iaAirxMg1Dmk5i1uFz-R9ip3fqA4j6ipFKhI='
    # 默认不开启代理
    proxy = None
    # 检测自己频道最近100条消息是否已经包含该资源
    checknum = 500
    # 对网盘链接有效性检测
    linkvalidtor = False
    # 允许转发今年之前的资源
    past_years = False
    TGForwarder(api_id, api_hash, string_session, channels_groups_monitor, forward_to_channel, limit, replies_limit, kw,
                ban, only_send, nokwforwards, fdown, download_folder, proxy, checknum, linkvalidtor, replacements, channel_match, hyperlink_text, past_years).run()
