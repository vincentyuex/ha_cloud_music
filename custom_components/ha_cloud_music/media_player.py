import json
import os
import logging
import voluptuous as vol
import requests
import time 
import datetime
import random

from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import track_time_interval
from homeassistant.components.http import HomeAssistantView
from aiohttp import web
from aiohttp.web import FileResponse
from typing import Optional
from homeassistant.helpers.state import AsyncTrackStates
from urllib.request import urlopen

_LOGGER = logging.getLogger(__name__)
############## 日志记录
_DEBUG = False
def _log(*arg):
    if _DEBUG:
        _LOGGER.info(*arg)

def _log_info(*arg):
    _LOGGER.info(*arg)

# 获取重写向后的地址
def get_redirect_url(url):
    # 请求头，这里我设置了浏览器代理
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 Safari/537.36'}
    # 请求网页
    response = requests.get(url, headers=headers)
    result_url = response.url
    if result_url == 'https://music.163.com/404':
        return None
    return result_url

###################媒体播放器##########################
from homeassistant.components.media_player import (
    MediaPlayerDevice, PLATFORM_SCHEMA)
from homeassistant.components.media_player.const import (
    MEDIA_TYPE_MUSIC,MEDIA_TYPE_URL, SUPPORT_PAUSE, SUPPORT_PLAY, SUPPORT_NEXT_TRACK, SUPPORT_PREVIOUS_TRACK, SUPPORT_TURN_ON, SUPPORT_TURN_OFF,
    SUPPORT_PLAY_MEDIA, SUPPORT_STOP, SUPPORT_VOLUME_MUTE, SUPPORT_VOLUME_SET, SUPPORT_SELECT_SOURCE, SUPPORT_CLEAR_PLAYLIST, SUPPORT_STOP, 
    SUPPORT_SELECT_SOUND_MODE, SUPPORT_SHUFFLE_SET, SUPPORT_SEEK, SUPPORT_VOLUME_STEP)
from homeassistant.const import (
    CONF_NAME, STATE_IDLE, STATE_PAUSED, STATE_PLAYING, STATE_OFF, STATE_UNAVAILABLE)
import homeassistant.helpers.config_validation as cv
import homeassistant.util.dt as dt_util
from homeassistant.helpers import discovery, device_registry as dr

SUPPORT_VLC = SUPPORT_PAUSE | SUPPORT_VOLUME_SET | SUPPORT_VOLUME_MUTE | SUPPORT_STOP | SUPPORT_SELECT_SOUND_MODE | SUPPORT_TURN_ON | SUPPORT_TURN_OFF | \
    SUPPORT_PLAY_MEDIA | SUPPORT_PLAY | SUPPORT_STOP | SUPPORT_NEXT_TRACK | SUPPORT_PREVIOUS_TRACK | SUPPORT_SELECT_SOURCE | SUPPORT_CLEAR_PLAYLIST | \
    SUPPORT_SHUFFLE_SET | SUPPORT_SEEK | SUPPORT_VOLUME_STEP

# 定时器时间
TIME_BETWEEN_UPDATES = datetime.timedelta(seconds=1)
###################媒体播放器##########################


VERSION = '1.0.5.2'
DOMAIN = 'ha_cloud_music'

_hass = None

#
# 读取所有静态文件
#
#
allpath=[]
allname=[]
def getallfile(path):
    allfilelist=os.listdir(path)
    # 遍历该文件夹下的所有目录或者文件
    for file in allfilelist:
        filepath=os.path.join(path,file)
        # 如果是文件夹，递归调用函数
        if os.path.isdir(filepath):
            getallfile(filepath)
        # 如果不是文件夹，保存文件路径及文件名
        elif os.path.isfile(filepath):
            allpath.append(filepath)
            allname.append(file)
    return allpath, allname

__dirname = os.path.dirname(__file__)
files, names = getallfile(__dirname+'/dist')

extra_urls = []
for file in files:
    extra_urls.append('/'+ DOMAIN + '/' + VERSION + file.replace(__dirname,'').replace('\\','/'))

##### 网关控制
class HassGateView(HomeAssistantView):
    """View to handle Configuration requests."""

    url = '/' + DOMAIN
    name = DOMAIN
    extra_urls = extra_urls
    requires_auth = False

    async def get(self, request):    
        # _LOGGER.info(request.rel_url.raw_path)
        return FileResponse(os.path.dirname(__file__) + request.rel_url.raw_path.replace(self.url + '/' + VERSION,''))

    async def post(self, request):
        """Update state of entity."""
        response = await request.json()
        return self.json(response)

        
##### 安装平台
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional("sidebar_title", default="云音乐"): cv.string,
    vol.Optional("sidebar_icon", default="mdi:music"): cv.string,
    # 网易云音乐用户ID
    vol.Optional("uid", default=""): cv.string,
    # 显示模式 全屏：fullscreen
    vol.Optional("show_mode", default="default"): cv.string
})

def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the vlc platform."""
    _LOGGER.info('''
-------------------------------------------------------------------
    ha_cloud_music云音乐插件【作者QQ：635147515】
    
    版本：''' + VERSION + '''    
    
    这是一个网易云音乐的HomeAssistant播放器插件
    
    https://github.com/shaonianzhentan/ha_cloud_music
-------------------------------------------------------------------''')    
    global _hass
    _hass = hass
    _hass.http.register_view(HassGateView)
    vlcDevice = VlcDevice(hass)
    add_entities([vlcDevice])

    # 注册服务load
    hass.services.register(DOMAIN, 'load', vlcDevice.load_songlist)

    # 添加到侧边栏
    coroutine = hass.components.frontend.async_register_built_in_panel(
        "iframe",
        config.get("sidebar_title"),
        config.get("sidebar_icon"),
        DOMAIN,
        {"url": "/" + DOMAIN+"/" + VERSION + "/dist/index.html?ver=" + VERSION 
        + "&show_mode=" + config.get("show_mode")
        + "&uid=" + config.get("uid")},
        require_admin=True,
    )
    try:
        if coroutine != None:
            coroutine.send(None)
    except StopIteration:
        pass    
    return True   


###################内置VLC播放器##########################
class VlcPlayer():
    def __init__(self): 
        import vlc
        self._instance = vlc.Instance()
        self._vlc = self._instance.media_player_new()
        self.state = STATE_IDLE
        self.attributes = {
            "volume_level": 1,
            "is_volume_muted": False,
            "media_duration": 0,
            "media_position_updated_at": None,
            "media_position": 0,
        }        
        self.ha_cloud_music = True
        event_manager = self._vlc.event_manager()
        event_manager.event_attach(vlc.EventType.MediaPlayerPositionChanged, self.update)
        _log_info("初始化内置VLC播放器")

    def update(self, position):
        try:
            import vlc        
            status = self._vlc.get_state()
            if status == vlc.State.Playing:
                self.state = STATE_PLAYING
            elif status == vlc.State.Paused:
                self.state = STATE_PAUSED
            else:
                self.state = STATE_IDLE
            
            media_duration = self._vlc.get_length() / 1000
            self.attributes['media_duration'] = media_duration
            self.attributes['media_position'] = self._vlc.get_position() * media_duration
            self.attributes['media_position_updated_at'] = datetime.datetime.now()
            self.attributes['volume_level'] = self._vlc.audio_get_volume() / 100
            self.attributes['is_volume_muted'] = (self._vlc.audio_get_mute() == 1)
            
            #_log_info(self.attributes)
        except Exception as e:
            print(e)

    def load(self, url):
        self._vlc.set_media(self._instance.media_new(url))
        self._vlc.play()
        self.state = STATE_PLAYING
                
    def play(self):
        if self._vlc.is_playing() == False:
            self._vlc.play()
        self.state = STATE_PLAYING
    
    def pause(self):
        if self._vlc.is_playing() == True:
            self._vlc.pause()
        self.state = STATE_PAUSED
    
    def volume_set(self, volume_level):
        self._vlc.audio_set_volume(int(volume_level) * 100)
        
###################媒体播放器##########################
class VlcDevice(MediaPlayerDevice):
    """Representation of a vlc player."""

    def __init__(self, hass):
        """Initialize the vlc device."""
        self._hass = hass
        self.music_playlist = None
        self.music_index = 0
        self._name = DOMAIN
        self._media_image_url = None
        self._media_title = None
        self._media_name = None
        self._media_artist = None
        self._media_album_name = None
        self._volume = None
        self._muted = None
        self._state = STATE_IDLE
        self._shuffle = False
        self._source_list = None
        self._source = None
        self._sound_mode_list = None
        self._sound_mode = None
        self._media_playlist = None
        self._media_position_updated_at = None
        self._media_position = 0
        self._media_duration = None
        # 错误计数
        self.error_count = 0
        self.loading = False
        # 定时器操作计数
        self.next_count = 0
        
        self._media = None
        # 是否启用定时器
        self._timer_enable = True
        # 定时器
        track_time_interval(hass, self.interval, TIME_BETWEEN_UPDATES)

    def interval(self, now):
        # 如果当前状态是播放，则进度累加（虽然我定时的是1秒，但不知道为啥2秒执行一次）
        if self._media != None:
            _log('当前时间：%s，当前进度：%s,总进度：%s', self._media_position_updated_at, self._media_position, self.media_duration)
            _log('源播放器状态 %s，云音乐状态：%s', self._media.state, self._state)
            
              # 没有进度的，下一曲判断逻辑
            if self._timer_enable == True:
                # 如果进度条结束了，则执行下一曲
                # 执行下一曲之后，15秒内不能再次执行操作
                if (self._source_list != None 
                    and len(self._source_list) > 0 
                    and self.media_duration > 0 
                    and ((self.media_duration > 3 and self.media_duration - 3 <= self.media_position) 
                        or (self._state != STATE_PLAYING and self.media_duration == 0 and self._media_position  == -3)) 
                    and self.next_count > 0):
                    _log('播放器更新 下一曲')
                    self.media_next_track()
                # 计数器累加
                self.next_count += 1
                if self.next_count > 100:
                    self.next_count = 100
                
                self.update()
            
            # 如果存在进度，则取源进度
            if 'media_position' in self._media.attributes:
                self._media_position = int(self._media.attributes['media_position'])
            # 如果当前是播放状态，则进行进度累加。。。
            elif self._state == STATE_PLAYING and self._media_position_updated_at != None:
                _media_position = self._media_position
                _today = (now - self._media_position_updated_at)
                _seconds = _today.seconds + _today.microseconds / 1000000.0
                _log('当前相差的秒：%s', _seconds)
                self._media_position += _seconds
            
            self._media_position_updated_at = now
            
    def update(self):        
        """Get the latest details from the device."""
        if self._sound_mode == None:
            self.init_sound_mode()            
            return False
        # 如果播放器列表有变化，则更新
        self.update_sound_mode_list() 
        
        # 使用内置VLC
        if self._sound_mode == "内置VLC播放器":
            self.init_vlc_player()            
        else:
            self.release_vlc_player()
            # 获取源播放器
            self._media = self._hass.states.get(self._sound_mode)
            # 如果状态不一样，则更新源播放器
            if self._state != self._media.state:
                self._hass.services.call('homeassistant', 'update_entity', {"entity_id": self._sound_mode})
                self._hass.services.call('homeassistant', 'update_entity', {"entity_id": 'media_player.'+DOMAIN})        
        
        self._media_duration = self.media_duration
        self._state = self._media.state
            
        return True

    @property
    def name(self):
        """Return the name of the device."""
        return self._name
    
    @property
    def friendly_name(self):
        """Return the name of the device."""
        return "网易云音乐"
    
    @property
    def media_image_url(self):
        """当前播放的音乐封面地址."""
        if self._media_image_url != None:            
            return self._media_image_url + "?param=500y500"
        return self._media_image_url
        
    @property
    def media_image_remotely_accessible(self) -> bool:
        """图片远程访问"""
        return True
    
    @property
    def source_list(self):
        """Return the name of the device."""
        return self._source_list   

    @property
    def source(self):
        """Return the name of the device."""
        return self._source       
        
    @property
    def sound_mode_list(self):
        """Return the name of the device."""
        return self._sound_mode_list

    @property
    def sound_mode(self):
        """Return the name of the device."""
        return self._sound_mode
    
    @property
    def media_album_name(self):
        """专辑名称."""
        return self._media_album_name
    
    @property
    def media_playlist(self):
        """当前播放列表"""
        return self._media_playlist
    
    @property
    def media_title(self):
        """歌曲名称."""
        return self._media_title
        
    @property
    def media_artist(self):
        """歌手"""
        return self._media_artist

    @property
    def state(self):
        """Return the state of the device."""
        # 如果状态是关，则显示idle
        if self._state == STATE_OFF or self._state == STATE_UNAVAILABLE:
            return STATE_IDLE

        return self._state

    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        if self._media == None:
            return None
        
        if 'volume_level' in self._media.attributes:
            return self._media.attributes['volume_level']
            
        return 1

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        if self._media == None:
            return None
        
        if 'is_volume_muted' in self._media.attributes:
            return self._media.attributes['is_volume_muted']
            
        return False

    @property
    def shuffle(self):
        """随机播放开关."""
        return self._shuffle

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        return SUPPORT_VLC

    @property
    def media_content_type(self):
        """Content type of current playing media."""
        return MEDIA_TYPE_MUSIC

    @property
    def media_duration(self):
        """Duration of current playing media in seconds."""
        if self._media == None:
            return None
        
        if 'media_duration' in self._media.attributes:
            return int(self._media.attributes['media_duration'])
            
        return 0

    @property
    def media_position(self):
        """Position of current playing media in seconds."""
        if self._media == None:
            return None
            
        return self._media_position
		
    @property
    def media_position_updated_at(self):
        """When was the position of the current playing media valid."""
        if self._media == None:
            return None
        
        if 'media_position_updated_at' in self._media.attributes:
            return self._media.attributes['media_position_updated_at']
            
        return self._media_position_updated_at

    def set_shuffle(self, shuffle):
        """禁用/启用 随机模式."""
        self._shuffle = shuffle

    def media_seek(self, position):
        """Seek the media to a specific location."""
        #track_length = self._vlc.get_length()/1000
        #self._vlc.set_position(position/track_length)
        return None

    def mute_volume(self, mute):
        """Mute the volume."""
        #self._vlc.audio_set_mute(mute)
        self._muted = mute

    def set_volume_level(self, volume):
        """Set volume level, range 0..1."""
        #self._vlc.audio_set_volume(int(volume * 100))
        #_log('设置音量：%s', volume)
        self.call('volume_set', {"volume": volume})
        #self._volume = volume

    def media_play(self):
        """Send play command."""
        #self._vlc.play()
        self.call('media_play')
        self._state = STATE_PLAYING

    def media_pause(self):
        """Send pause command."""
        #self._vlc.pause()
        self.call('media_pause')
        self._state = STATE_PAUSED

    def media_stop(self):
        """Send stop command."""
        #self._vlc.stop()
        self.call('media_stop')
        self._state = STATE_IDLE
		
    def play_media(self, media_type, media_id, **kwargs):
        """Play media from a URL or file."""        
        #_log('类型：%s', media_type)                
        if media_type == MEDIA_TYPE_MUSIC:
            self._timer_enable = False
            url = media_id
        elif media_type == 'music_load':                    
            self.music_index = int(media_id)
            music_info = self.music_playlist[self.music_index]
            url = self.get_url(music_info)
        elif media_type == MEDIA_TYPE_URL:
            _log('加载播放列表链接：%s', media_id)
            res = requests.get(media_id)
            play_list = res.json()
            self._media_playlist = play_list
            self.music_playlist = play_list
            music_info = self.music_playlist[0]
            url = self.get_url(music_info)
            #数据源
            source_list = []
            for index in range(len(self.music_playlist)):
                music_info = self.music_playlist[index]
                source_list.append(str(index + 1) + '.' + music_info['song'] + ' - ' + music_info['singer'])
            self._source_list = source_list
            #初始化源播放器
            self.media_stop()
            _log('绑定数据源：%s', self._source_list)
        elif media_type == 'music_playlist':
            _log('初始化播放列表')
            
            # 如果是list类型，则进行操作
            if isinstance(media_id, list):            
                self._media_playlist = json.dumps(media_id)
                self.music_playlist = media_id
                self.music_index = 0
            else:
                dict = json.loads(media_id)    
                self._media_playlist = dict['list']
                self.music_playlist = json.loads(self._media_playlist)
                self.music_index = dict['index']
                
            music_info = self.music_playlist[self.music_index]
            url = self.get_url(music_info)
            #数据源
            source_list = []
            for index in range(len(self.music_playlist)):
                music_info = self.music_playlist[index]
                source_list.append(str(index + 1) + '.' + music_info['song'] + ' - ' + music_info['singer'])
            self._source_list = source_list
            #初始化源播放器
            self.media_stop()
        else:
            _LOGGER.error(
                "不受支持的媒体类型 %s",media_type)
            return
        _log_info('title：%s ，play url：%s' , self._media_name, url)
        
        # 默认为music类型，如果指定视频，则替换
        play_type = "music"
        if 'media_type' in music_info and music_info['media_type'] == 'video':
            play_type = "video"
        # 如果没有url则下一曲（如果超过3个错误，则停止）
        # 如果是云音乐播放列表 并且格式不是mp3，则下一曲
        elif url == None or (media_type == 'music_load' and url.find(".mp3") < 0):
           self.notification("没有找到【" + self._media_name + "】的播放链接，自动为您跳到下一首", "load_song_url")
           self.error_count = self.error_count + 1
           if self.error_count < 3:
             self.media_next_track()
           return
        # 重置错误计数
        self.error_count = 0
        # 重置播放进度
        self._media_position = 0
        self._media_position_updated_at = None
        #播放音乐
        self.call('play_media', {"url": url,"type": play_type})

    def media_next_track(self):
        self.music_index = self.music_index + 1
        _log('下一曲：%s', self.music_index)
        self.next_count = -15        
        self.music_load()

    def media_previous_track(self):
        self.music_index = self.music_index - 1
        _log('上一曲：%s', self.music_index)
        self.music_load()
    
    def select_source(self, source):
        _log('选择源：%s', source)
        #选择播放
        self._state = STATE_IDLE
        self.music_index = self._source_list.index(source)
        self.play_media('music_load', self.music_index)
        
    def select_sound_mode(self, sound_mode):        
        self._sound_mode = sound_mode
        self._state = STATE_IDLE
        self.save_sound_mode()
        _log('选择声音模式：%s', sound_mode)
    
    def clear_playlist(self):
        _log('清除播放列表')
        self.music_playlist = None
        self.music_index = 0
        self._media_title = None
        self._media_name = None
        self._source_list = None
        self._media_album_name = None
        self._source = None
        self._shuffle = False
        self._media_image_url = None
        self._media_artist = None
        self._media_playlist = None
        self._media_position_updated_at = None
        self._media_position = 0
        self._media_duration = None                
        self.media_stop()
                
    def turn_off(self):
        """Send stop command."""
        self.clear_playlist()
    
    def notification(self, message, type):
        self._hass.services.call('persistent_notification', 'create', {"message": message, "title": "云音乐", "notification_id": "ha-cloud-music-" + type})
    
    ## 自定义方法
    # 加载播放列表
    def load_songlist(self, call):                
        _id = call.data['id']        
        _type = "playlist"
        if 'type' in call.data:
            _type = call.data['type']
        
        if self.loading == True:
            self.notification("正在加载歌单，请勿重复调用服务", "load_songlist")
            return
        self.loading = True        
        
        try:
            if _type == "playlist":
                _log_info("加载歌单列表，ID：%s", _id)
                # 获取播放列表
                res = requests.get('https://api.jiluxinqing.com/api/music/playlist/detail?id=' + str(_id))
                obj = res.json()
                if obj['code'] == 200:
                    _list = obj['playlist']['tracks']
                    _newlist = map(lambda item: {
                        "id": int(item['id']),
                        "name": item['name'],
                        "album": item['al']['name'],
                        "image": item['al']['picUrl'],
                        "duration": int(item['dt']) / 1000,
                        "url": "https://music.163.com/song/media/outer/url?id=" + str(item['id']),
                        "song": item['name'],
                        "singer": len(item['ar']) > 0 and item['ar'][0]['name'] or '未知'
                        }, _list)            
                    #_log_info(_result)
                    self.play_media('music_playlist', list(_newlist))
                    self.notification("正在播放歌单【"+obj['playlist']['name']+"】", "load_songlist")
                else:
                    # 这里弹出提示
                    self.notification("没有找到id为【"+_id+"】的歌单信息", "load_songlist")
            elif _type == "djradio":
                _log_info("加载电台列表，ID：%s", _id)
                # 获取播放列表
                res = requests.get('https://api.jiluxinqing.com/api/music/dj/program?rid='+str(_id)+'&limit=50')
                obj = res.json()
                if obj['code'] == 200:
                    _list = obj['programs']
                    _newlist = map(lambda item: {
                        "id": int(item['mainSong']['id']),
                        "name": item['name'],
                        "album": item['coverUrl'],
                        "image": item['mainSong']['album']['picUrl'],
                        "duration": int(item['mainSong']['duration']) / 1000,
                        "song": item['name'],
                        "type": "djradio",
                        "singer": item['dj']['nickname']
                        }, _list)            
                    #_log_info(_result)
                    self.play_media('music_playlist', list(_newlist))
                    self.notification("正在播放电台【"+_list[0]['dj']['brand']+"】", "load_songlist")
                else:
                    # 这里弹出提示
                    self.notification("没有找到id为【"+_id+"】的歌单信息", "load_songlist")
            
        except Exception as e:
            self.notification("加载歌单的时候出现了异常", "load_songlist")
        finally:
            # 这里重置    
            self.loading = False
        
    # 更新播放器列表
    def update_sound_mode_list(self):
        entity_list = self._hass.states.entity_ids('media_player')
        if len(entity_list) != len(self._sound_mode_list):
            self.init_sound_mode()
        
    # 保存当前选择的播放器
    def save_sound_mode(self):
        filename = os.path.dirname(__file__) + '/sound_mode.json'
        entity_value = {'state': self._sound_mode}
        with open(filename, 'w') as f_obj:
            json.dump(entity_value, f_obj)
    
    # 读取当前保存的播放器
    def init_sound_mode(self):
        filename = os.path.dirname(__file__) + '/sound_mode.json'
        sound_mode = None
        if os.path.exists(filename) == True:
            with open(filename, 'r') as f_obj:
                entity = json.load(f_obj)
                sound_mode = entity['state']
                
        # 过滤云音乐
        entity_list = self._hass.states.entity_ids('media_player')
        filter_list = filter(lambda x: x.count('media_player.' + DOMAIN) == 0, entity_list)
        _list = list(filter_list)
        if self.supported_vlc == True:
            _list.insert(0, "内置VLC播放器")
        
        self._sound_mode_list = _list
        
        # 如果保存的是【内置VLC播放器】，则直接加载
        if sound_mode == "内置VLC播放器":
           self._sound_mode = "内置VLC播放器"
           self.init_vlc_player()
           return        
        
        if len(self._sound_mode_list) > 0:
            # 判断存储的值是否为空
            if sound_mode != None and self._sound_mode_list.count(sound_mode) == 1:
                self._sound_mode = sound_mode
            elif self.supported_vlc == True:
                self._sound_mode = "内置VLC播放器"
                self.init_vlc_player()
            else:
                self._sound_mode = self._sound_mode_list[0]
        elif self.supported_vlc == True:
            self._sound_mode = "内置VLC播放器"
            self.init_vlc_player()
        #_log(self._sound_mode_list)
       
    def get_url(self, music_info):
        self._media_name = music_info['song'] + ' - ' + music_info['singer']
        self._source = str(self.music_index + 1) + '.' + self._media_name
        # 歌名
        self._media_title = music_info['song']
        # 歌手
        self._media_artist = music_info['singer']
        # 设置图片
        if 'image' in music_info:
            self._media_image_url = music_info['image']
        # 设置专辑名称
        if 'album' in music_info:
            self._media_album_name = music_info['album']
        
        if 'clv_url' in music_info:
           return music_info['clv_url']
        elif 'type' in music_info and music_info['type'] == 'djradio':
           res = requests.get("https://api.jiluxinqing.com/api/music/song/url?id=" + str(music_info['id']))
           obj = res.json()
           url = obj['data'][0]['url']
           return url
        else:           
           return get_redirect_url(music_info['url'])
    
    def call(self, action, info = None):
        dict = {"entity_id": self._sound_mode}
        if info != None:
           if 'url' in info:
              dict['media_content_id'] = info['url']
           if 'type' in info:
              dict['media_content_type'] = info['type']
           if 'volume' in info:
              dict['volume_level'] = info['volume']
        
        #调用服务
        _log('调用服务：%s', action)
        _log(dict)
                
        if self._sound_mode == "内置VLC播放器":
            if action == "play_media":
                self._media.load(info['url'])
            elif action == "media_pause":
                self._media.pause()
            elif action == "media_play":
                self._media.play()
            elif action == "volume_set":
                self._media.volume_set(info['volume'])
        else:
            self._hass.services.call('media_player', action, dict)
            self._hass.services.call('homeassistant', 'update_entity', {"entity_id": self._sound_mode})
            self._hass.services.call('homeassistant', 'update_entity', {"entity_id": 'media_player.'+DOMAIN})
                    
    def music_load(self):
        if self.music_playlist == None:
           _log('结束播放，没有播放列表')
           return
        self._timer_enable = True
        playlist_count = len(self.music_playlist)
        if self.music_index >= playlist_count:
           self.music_index = 0
        elif self.music_index < 0:
           self.music_index = playlist_count - 1

        # 如果启用了随机模式，则每次都生成随机值
        if self._shuffle == True:
           self.music_index = random.randint(0, playlist_count - 1)
           _log_info("当前总共有 %s 首音乐，随机播放第 %s 首", playlist_count, self.music_index)

        self.play_media('music_load', self.music_index)
    
    
    ######################内置VLC播放器相关方法################################
    @property
    def supported_vlc(self):
        """判断是否支持vlc模块."""
        try:
            import vlc
            return True
        except Exception as e:
            return False
    
    # 初始化内置VLC播放器
    def init_vlc_player(self):
        try:
            if self._media == None or hasattr(self._media, 'ha_cloud_music') == False:
                self._media = VlcPlayer()
        except Exception as e:
            print("【初始化内置VLC播放器】出现错误", e)            

    # 释放vlc对象
    def release_vlc_player(self):        
        if self._media != None and hasattr(self._media, 'ha_cloud_music') == True:
            self._media._vlc.release()
            self._media._instance.release()
###################媒体播放器##########################