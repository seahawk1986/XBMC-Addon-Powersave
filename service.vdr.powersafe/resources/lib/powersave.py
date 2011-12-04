import sys, os, socket, telnetlib, time
import xbmc, xbmcaddon, xbmcgui, xbmcplugin

Addon = xbmcaddon.Addon(id="vdr.powersave")



class Main:
	_base = sys.argv[0]
	_enum_forerun = [1,2,5,10,15,20]
	_enum_overrun = [1,2,5,10,15,20]
	_enum_idle= [5,10,15,20,25,30,40,50,60,90,120,180,240,300,360,420,480,540,600]
	_sleep_interval = 10000
	_poll_interval = 6
	_timers = {}
	_lastWakeup = 0
	_idleTime = 0
	_lastIdleTime = 0
	_realIdleTime = 0
	_isLoggedOn = False
	_lastPlaying = False
	_isPlaying = False
	_lastRecording = False
	_isRecording = False

	# main routine
	def __init__(self):
		print "vdr.powersave: Plugin started"
		self.getSettings()
		self.getTimers()
		pollCounter = self._poll_interval
		# main loop
		while (not xbmc.abortRequested):
			# reload timers periodically
			if (pollCounter > self._poll_interval):
				pollCounter = 0
				self.getTimers()
			else:
				pollCounter = pollCounter + 1
				
			# set wakeup
			self.setWakeup()
			
			# time warp calculations demands to have our own idle timers
			self._lastIdleTime = self._idleTime
			self._idleTime = xbmc.getGlobalIdleTime()
			if (self._idleTime > self._lastIdleTime):
				self._realIdleTime = self._realIdleTime + (self._idleTime - self._lastIdleTime)
			else:
				self._realIdleTime = self._idleTime

			# notice changes in playback
			self._lastPlaying = self._isPlaying
			self._isPlaying = xbmc.Player().isPlaying()
			
			# now this one is tricky: a playback ended, idle would suggest to powersave, but we set the clock back for overrun. 
			# Otherwise xbmc could sleep instantly at the end of a movie
			if (self._lastPlaying  == True) & (self._isPlaying == False) & (self._realIdleTime >= self.settings['vdrps_sleepmode_after']):
				self._realIdleTime = self.settings['vdrps_sleepmode_after'] - self.settings['vdrps_overrun']
				#print "vdr.powersave: playback stopped!"

			# notice changes in recording
			self._lastRecording = self._isRecording
			self._isRecording = self.getIsRecording()

			# same trick, for recording issues - gives time to postprocess
			if (self._lastRecording  == True) & (self._isRecording == False) & (self._realIdleTime >= self.settings['vdrps_sleepmode_after']):
				self._realIdleTime = self.settings['vdrps_sleepmode_after'] - self.settings['vdrps_overrun']

			
			
			print "vdr.powersave: Mark"

			# powersave checks ...
			if (self.settings['vdrps_sleepmode'] > 0) & \
			   (self._realIdleTime >= self.settings['vdrps_sleepmode_after']):
				# sleeping time already?
				if (self._isPlaying):
					print "vdr.powersave: powersave postponed - xbmc is playing ..."
				elif (self._isRecording):
					print "vdr.powersave: powersave postponed - vdr is recording ..."
				elif (self.getIsRecordPending()):
					print "vdr.powersave: powersave postponed - record upcomming ..."
				else:
					if (self.settings['vdrps_sleepmode'] == 1):
						#print "vdr.powersave: initiating sleepmode S3 ..."
						xbmc.executebuiltin('Suspend')
					elif (self.settings['vdrps_sleepmode'] == 2):
						#print "vdr.powersave: initiating sleepmode S4 ..."
						xbmc.executebuiltin('Hibernate')
					elif (self.settings['vdrps_sleepmode'] == 3):
						#print "vdr.powersave: initiating powerdown ..."
						xbmc.executebuiltin('Powerdown')
			
			
			# Disabled due to bugged service abort on logouts
			# are we logged on? (Dialog <> 10029)			
			#self._isLoggedOn = (xbmcgui.getCurrentWindowId()<>10029)
			# check for automatic logout ...
			#if (self.settings['vdrps_autologout'] == "true") & \
			   #(self._idleTime > self.settings['vdrps_autologout_after']) & \
			   #self._isLoggedOn:
				## logging out is safe
				#xbmc.executebuiltin('System.LogOff')
			
			
			# sleep a little ...
			xbmc.sleep(self._sleep_interval)
		# last second check
		self.getTimers()
		# last second alarm clock
		self.setWakeup()
		print "vdr.powersave: Plugin exited"
		
	# get settings from xbmc
	def getSettings(self):
		print "vdr.powersave: Getting settings ..."
		self.settings = {}
		self.settings['vdrps_host'] = Addon.getSetting('vdrps_host')
		self.settings['vdrps_port'] = int(Addon.getSetting('vdrps_port'))
		self.settings['vdrps_forerun'] = self._enum_forerun[int(Addon.getSetting('vdrps_forerun'))] * 60
		self.settings['vdrps_wakecmd'] = Addon.getSetting('vdrps_wakecmd')
		self.settings['vdrps_overrun'] = self._enum_forerun[int(Addon.getSetting('vdrps_overrun'))] * 60
		# Disabled due to bugged service abort on logouts
		#self.settings['vdrps_autologout'] = Addon.getSetting('vdrps_autologout')
		#self.settings['vdrps_autologout_after'] = self._enum_idle[int(Addon.getSetting('vdrps_autologout_after'))] * 60
		self.settings['vdrps_sleepmode'] = int(Addon.getSetting('vdrps_sleepmode'))
		self.settings['vdrps_sleepmode_after'] = self._enum_idle[int(Addon.getSetting('vdrps_sleepmode_after'))] * 60
		self.settings['vdrps_dailywakeup'] = Addon.getSetting('vdrps_dailywakeup')
		self.settings['vdrps_dailywakeup_time'] = int(Addon.getSetting('vdrps_dailywakeup_time')) * 1800

	# get timers from vdr
	def getTimers(self):
		#print "vdr.powersave: Getting timers ..."
		# contact SVDRP and parse resopnse
		raw = self._querySVDRP(self.settings['vdrps_host'], self.settings['vdrps_port'])
		# parse when get a response
		if (raw != None):
			self._parseSVDRP(raw)

	# set the alarm clock if necessary
	def setWakeup(self):
		# calculate next wakeup time
		stampWakeup = self.getMostRecentTimer() - self.settings['vdrps_forerun']
		stampNow = int(time.time())
		# some extra calculations for daily wakeing
		if (self.settings['vdrps_dailywakeup'] == "true"):
			# extract date and time only
			tupleNow = time.localtime(stampNow)
			stampTimeOnly = (tupleNow.tm_hour*3600)+(tupleNow.tm_min*60)+tupleNow.tm_sec
			stampDateOnly = time.mktime((tupleNow.tm_year,tupleNow.tm_mon,tupleNow.tm_mday,0,0,0,tupleNow.tm_wday,tupleNow.tm_yday,tupleNow.tm_isdst))

			# wake me today, or tomorrow?
			if (self.settings['vdrps_dailywakeup_time'] > stampTimeOnly):
				stampDailyWakeup = stampDateOnly + self.settings['vdrps_dailywakeup_time']
			else:
				# add a whole day
				stampDailyWakeup = stampDateOnly + self.settings['vdrps_dailywakeup_time'] + 86400

			# daily wakeup is before next timer, so set the alarm clock to it
			if (stampDailyWakeup<stampWakeup):
				stampWakeup = stampDailyWakeup
		
		# is it in the future and not already set?
		if (stampWakeup>stampNow) & (stampWakeup <> self._lastWakeup):
			# yes we do have to wakeup
			print "vdr.powersave: Wake up on timestamp %d (%s)" % (stampWakeup, time.asctime(time.localtime(stampWakeup)) )
			# call the alarm script
			os.system("%s %d" % (self.settings['vdrps_wakecmd'],stampWakeup))
			# remember the stamp, not to call alarm script twice with the same value
			self._lastWakeup = stampWakeup
			
	# contact SVDRP service and get raw timers
	def _querySVDRP(self, host, port):
		try:
			tndata = None
			# getting in contact
			tnsession = telnetlib.Telnet(host,port,5)
			try:
				# sending commands
				tnsession.write("LSTT\n")
				tnsession.write("QUIT\n")
				# getting data
				tndata = tnsession.read_until("closing connection")
			finally:
				# clean up our mess, and get back
				tnsession.close()
				return tndata

		except:
			# made a boo boo
			print "vdr.powersave: cannot get list of timers from %s:%s " % (host, port)
			return None
			
	# this function parses the SVDRP session dump for timers and returns a dictonary with status
	def _parseSVDRP(self, raw):
		# empty result list
		timers = {}
		# loop thru lines
		for line in raw.splitlines():
			# as we know timers getting returned with status 250 (ok) 
			if line.startswith("250"):
				try:
					# get into the fields
					fields = line[4:].split(":")
					# check the timer status (flags 1: enabled, 2, instant record, 4, vps, 8: active)
					timer_status = fields[0].split(" ")[1]
					# decode starting time
					timer_start = int(time.mktime(time.strptime(fields[2]+fields[3], "%Y-%m-%d%H%M")))
					# fill the timer dictonary
					if timer_start>0:
						timers[timer_start] = int(timer_status)
				except: 
					# some lines may fail
					print "vdr.powersave: unable to parse line '%s' " % (line)
		self._timers = timers

	# returns if any timer is actually recording
	def getIsRecording(self):
		for status in self._timers.values():
			if (status & 8) == 8:
				return True
		return False;
		
	# returns if a record is upcomming within forerun, or idle time to prevent powersave 
	def getIsRecordPending(self):
		# decide which period lasts longer
		if (self.settings['vdrps_forerun'] > self.settings['vdrps_sleepmode_after']):
			delta = self.settings['vdrps_forerun']
		else:
			# odd people may set the recording prerun smaller than idle time
			delta = self.settings['vdrps_sleepmode_after']
		# we need the stamps
		stamps = self._timers.keys()
		stampNow = int(time.time())
		for stamp in stamps:
			if (self._timers[stamp] & 1 == 1) & (stamp-delta < stampNow ):
				# there is a record upcomming
				return True
		return False

	# this returns the most recent enabled timestamp, or None
	def getMostRecentTimer(self):
		# we need a sorted list of the timestamps
		stamps = self._timers.keys()
		stamps.sort()
		# now search for the first enabled one
		for stamp in stamps:
			if self._timers[stamp] & 1 == 1:
				return int(stamp)
		return 0;
