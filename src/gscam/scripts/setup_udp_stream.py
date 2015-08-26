#!/usr/bin/env python

import rospy
import socket
from os import system

rospy.init_node('setup_udp_stream')

host = rospy.get_param('~host')
port = 10003
size = 1024
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((host,port))
s.send('hello')
all_data = ""
while not all_data.endswith('\n'):
	data = s.recv(size)
	all_data += data
s.close()

system('hping3 -c 1 -2 -s 5000 -p ' + all_data.strip() + ' ' + host)
print 'Received:', all_data