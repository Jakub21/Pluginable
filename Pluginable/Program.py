from Pluginable.Settings import Settings
from Pluginable.Namespace import Namespace
from Pluginable.Logger import *
from Pluginable.Event import StockEvent
from Pluginable.Compiler import Compiler
from Pluginable.FileManager import CleanPyCache
from Pluginable.TpsMonitor import TpsMonitor
import Pluginable.MultiHandler as mh
import multiprocessing as mpr
from time import sleep

class Program(LogIssuer):
  def __init__(self, progName=''):
    self.progName = progName
    self.manager = mpr.Manager()
    self.setIssuerData('kernel', 'Program')
    self.tpsMon = TpsMonitor(Settings.Kernel.MaxProgramTicksPerSec)
    self.quitting = False
    self.tick = 0
    self.evntQueue = self.manager.Queue()
    self.plugins = Namespace()
    self.evntHandlers = {
      'AddHandler': [self.addEvtHandler],
      'PluginError': [self.onError],
      'StopProgram': [self.quit],
      'InitDoneState': [self.setInitDoneFlag],
    }
    self.noEvtHandlerWarns = []
    self.compiler = Compiler(self)
    self.phase = 'instance'
    self.settings = {
      'StartTime': Settings.StartTime
    }
    self.pluginConfigs = {}

  def customSettings(self, data):
    if self.phase != 'instance':
      Error(self, 'Settings can not be changed after preload method was called')
      exit()
    Note(self, 'Adding custom entries in program settings')
    try: Settings.Custom
    except: Settings.Custom = Namespace()
    for key, val in data.items():
      self.settings[f'Custom.{key}'] = val

  def updateSettings(self, data):
    if self.phase != 'instance':
      Error(self, 'Settings can not be changed after preload method was called')
      exit()
    Note(self, 'Changing settings')
    delKeys = []
    for key, val in data.items():
      try:
        eval(f'Settings.{key}')
        self.settings[key] = val
      except (KeyError, AttributeError):
        if not key.startswith('Custom.'):
          Warn(self, f'Setting "{key}" does not exist')
          delKeys += [key]
          continue
    for key in delKeys:
      del data[key]
    self.settings['StartTime'] = Settings.StartTime

  def configPlugin(self, pluginKey, data):
    if self.phase != 'preloaded':
      Error(self, 'Plugins can be configured only after preload method was called')
      exit()
    self.pluginConfigs[pluginKey] = data

  def preload(self):
    for key, val in self.settings.items():
      if type(val) == str: val = f'"{val}"'
      elif type(val) == datetime:
        val = f"datetime.strptime('{val}', '%Y-%m-%d %H:%M:%S.%f')"
      exec(f'Settings.{key} = {val}')
    Info(self, 'Starting plugins preload')
    self.compiler.compile()
    self.phase = 'preloaded'

  def run(self):
    self.compiler.load()
    Note(self, 'Starting program')
    self.phase = 'running'
    while not self.quitting:
      try:
        self.handleAllEvents()
        self.tpsMon.tick()
      except KeyboardInterrupt: break
      except: self.phase = 'exception'; raise
    self.quit()

  def handleAllEvents(self):
    while not mh.empty(self.evntQueue):
      event = mh.pop(self.evntQueue)
      try: hndPlugins = self.evntHandlers[event.id]
      except KeyError:
        if event.id not in self.noEvtHandlerWarns:
          Warn(self, f'Event "{event.id}" has no handlers assigned')
          self.noEvtHandlerWarns.append(event.id)
        continue
      except AttributeError:
        Warn(self, f'There was a boolean in event queue')
        continue
      for handler in hndPlugins:
        if callable(handler): handler(event) # Execute internal handler
        else: # Send event to all plugin executors with handlers
          mh.push(self.plugins[handler].queue, event)
    self.tpsMon.tick()

  def quit(self, event=None):
    # set program flags
    if self.phase == 'quitting': return
    if self.phase != 'exception': self.phase = 'quitting'
    Note(self, 'Starting cleanup')
    self.quitting = True
    # quit plugins
    for key, plugin in self.plugins.items():
      if self.phase == 'exception': mh.set(plugin.quitStatus, 2)
      else:
        mh.set(plugin.quitStatus, 1)
        mh.push(plugin.queue, StockEvent('Quit'))
    sleep(0.3)
    for key, plugin in self.plugins.items():
      plugin.proc.join()
    # working directory cleanup
    Info(self, 'Deleting temporary files')
    CleanPyCache()
    self.compiler.removeTemp()

  # Methods called by plugins' executors

  def addEvtHandler(self, event):
    try: self.evntHandlers[event.eventKey] += [event.plugin]
    except KeyError: self.evntHandlers[event.eventKey] = [event.plugin]

  def setInitDoneFlag(self, event):
    plugin = self.plugins[event.pluginKey]
    plugin.initDone = event.state
    plugin.inputNodes = event.nodes
    allDone = True
    allNodes = {}
    for plugin in self.plugins.values():
      if not plugin.initDone: allDone = False; break
      allNodes.update(plugin.inputNodes)
    if allDone:
      Note(self, f'All plugins initialized')
      for plugin in self.plugins.values():
        mh.push(plugin.queue, StockEvent('ProgramInitDone', nodes=allNodes))

  def onError(self, event):
    prefix = ['PluginReset', 'Critical'][event.critical]
    Error(self, f'{prefix}: {event.message}\n' + event.traceback + \
      f'{event.name}: {event.info}')
    self.phase = 'exception'
    if event.critical: self.quit()
