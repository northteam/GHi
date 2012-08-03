#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (C) 2012 smallevilbeast
# Author:     smallevilbeast <houshao55@gmail.com>
# Maintainer: smallevilbeast <houshao55@gmail.com>
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import sys
import urllib
import urllib2
import httplib
import urlparse
import re
import cookielib
import time
import random
import string
import cgi


try:
    import simplejson as json
except ImportError:    
    import json
    
import socket    
socket.setdefaulttimeout(40) # 40s

from logger import Logger
from xdg_support import get_cache_file

def timestamp():
    return int(time.time() * 1000)

def radix(n, base=36):
    digits = string.digits + string.lowercase
    def shortDiv(n, acc=list()):
        q, r = divmod(n, base)
        return [r] + acc if q == 0 else shortDiv(q, [r] + acc)
    return ''.join(digits[i] for i in shortDiv(n))

def timechecksum():
    return radix(timestamp())

__cookies__ = get_cache_file("cookie.txt")

class HiLib(Logger):
    def __init__(self, username, password):
        
        self.username = username.decode("utf-8").encode("gbk")
        self.password = password
        
        # 保存cookie
        cj = cookielib.LWPCookieJar(__cookies__)
        cookie_handler = urllib2.HTTPCookieProcessor(cj)
        opener = urllib2.build_opener(cookie_handler)
        
        opener.addheaders = [
            ('User-agent', 'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/535.24 ' \
             '(KHTML, like Gecko) Chrome/19.0.1056.0 Safari/535.24'),]
        
        self.cookiejar = cj
        self.opener = opener
        self.seq = 0 
        self.apidata = dict()
        self.pickack = ""
        self.last_message_timestamp = 0
        
    def login(self, stage=0):
        self.apidata = dict()
        req = urllib2.Request("http://web.im.baidu.com/")
        ret = self.opener.open(req)
        ret.read() # Fix
        ret = self.api_request("check", v=30, time=timechecksum())        
        self.logdebug("Login check return value: %s", ret)
        
        # 登陆校验成功.
        if ret["result"] == "ok":
            self.cookiejar.save()
            self.loginfo("Login check success!")
            return True
        
        # 登陆校验失败(超过两次登陆校验)
        elif stage >= 2:
            self.loginfo("Login check failed!")
            return False
        assert ret['result'] == 'offline'
        req = urllib2.Request('http://passport.baidu.com/api/?login&tpl=mn&time=%d' % timestamp())
        data = self.opener.open(req).read().strip()[1:-1] # remove brackets
        data = eval(data, type('Dummy', (dict,), dict(__getitem__=lambda s,n:n))())
        if int(data["error_no"]) != 0:
            self.logdebug("Login passport error: %s", data)
            return False
        param_out = data["param_out"]
        param_in = data["param_in"]
        params = {v : param_out[k.replace("name", "contex")] for k, v in param_out.items() if k.endswith("_name")}
        params.update({v: param_in[k.replace("name", "value")] for k,v in param_in.items() if k.endswith("_name")})
        
        params["username"] = self.username
        params["password"] = self.password
        params["safeflg"]  = ""
        params["mem_pass"] = "on"
        if int(params["verifycode"]) == 1 and stage == 1:
            self.loginfo("Login check require verifycode")
            params["verifycode"] = self.get_verify_code()
            
        params['staticpage'] = 'http://web.im.baidu.com/popup/src/login_jump.htm'
        self.logdebug("After filing params: %s", params)

        req = urllib2.Request('https://passport.baidu.com/api/?login',
                              data=urllib.urlencode(params))
        html = self.opener.open(req).read()
        url = re.findall(r"encodeURI\('(.*?)'\)", html)[0]
        self.opener.open(url).read()
        
        # 二次登陆校验
        if stage == 0:
            self.loginfo("Begin second login check..")
        elif stage == 1:    
            self.loginfo("Begin three login check..")
        return self.login(stage=stage+1)
    
    def init(self):
        
        # 登陆后初始化.
        self.seq = 0
        guid = timechecksum()
        
        # API请求公用数据
        self.apidata = dict(v=30, session="", source=22, guid=guid,
                            seq=lambda : self.seq)
        
        # 开始登陆过程
        self.api_request("welcome", method="POST", extra_data={"from" : 0},
                         seq=self.seq, force="true")
        ret = self.api_request("init", method="POST", status="online")
        
        if ret["result"] == "ok":
            self.loginfo("Login ok: username=%s, nick=%s", ret["content"]["username"],
                         ret["content"]["nickname"])
            
        # 第一次 pick 自己是否登陆成功,  ack = 0
        self.pick()    
        ret = self.api_request("getmultiteaminfo")
        self.logdebug("Group: %s", ret)
        
        ret = self.api_request('getmultifriendlist', data="", seq=self.seq,
                       tid=0, page=0, field='relationship,username,showname,showtype,status')
        self.logdebug("Friends list:", ret)
        
    def pick(self):    
        ''' main callable func.'''
        ret = self.api_request("pick", type=23, flag=1, ack=self.pickack)
        if ret["result"] != "ok":
            if ret["result"] == "kicked":
                self.logerror("Kicked by system!")
            elif ret["result"] == "networkerror":
                self.log.fatal("Network error!")
            else:    
                self.logerror("Pick error: %s", ret)
        if ret["content"]:
            self.pickack = ret["content"]["ack"]
            for field in ret["content"]["fields"]:
                self.handle_pick_field(field)
                
    def handle_pick_field(self, field):            
        pass
        
    def get_verify_code(self):
        url = 'https://passport.baidu.com/?verifypic&t=%d' % timestamp()
        req = urllib2.Request(url)
        data = self.opener.open(req).read()
        with open("./pic.jpg", "wb") as fp:
            fp.write(data)
        return raw_input("piz input code > ").strip()    
        
    def api_request(self, api, method="GET", extra_data=dict(), retry_limit=2, **params):    
        url = urlparse.urljoin("http://web.im.baidu.com/", api)
        data = self.apidata.copy()
        data.update(extra_data)
        data.update(params)
        for key in data:
            if callable(data[key]):
                data[key] = data[key]()
            if isinstance(data[key], (list, tuple, set)):
                data[key] = ",".join(map(str, list(data[key])))
            if isinstance(data[key], unicode):    
                data[key] = data[key].encode("utf-8")
                
        if method == "GET":        
            query = urllib.urlencode(data)
            url = "%s?%s" % (url, query)
            req = urllib2.Request(url)
        elif method == "POST":
            body = urllib.urlencode(data)
            req = urllib2.Request(url, data=body)
            
        self.logdebug("API request url: %s", url)    
        start = time.time()    
        try:
            ret = self.opener.open(req)
        except Exception, e:    
            if retry_limit == 0:
                self.logdebug("API request error: url=%s error=%s",  url, e)
                return dict(result="network_error")
            else:
                retry_limit -= 1
                return self.api_request(api, method, extra_data, retry_limit, **params)
        raw = ret.read()
        try:
            data = json.loads(raw)
        except:    
            data = eval(raw, type("Dummy", (dict,), dict(__getitem__=lambda s,n: n))())
        self.logdebug("API response %s: %s TT=%.3fs", api, data, time.time() - start )
        return data

if __name__ == "__main__":    
    pass
