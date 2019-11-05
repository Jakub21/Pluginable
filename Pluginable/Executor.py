import multiprocessing as mpr
from Pluginable.Logger import Logger
from Pluginable.Namespace import Namespace
from Pluginable.Event import Event

class Executor(Logger):
  def __init__(self, plugin, forceQuit, plgnQueue, evntQueue, logLock):
    super().__init__((f'{plugin.scope}.{plugin.key}', 'Executor'), 'plugin', logLock)
    self.quitting = False
    self.plugin = plugin
    self.forceQuit = forceQuit
    self.plgnQueue = plgnQueue
    self.evntQueue = evntQueue
    self.plugin.executor = self
    self.evntHandlers = Namespace(
      cnfg = self.configure,
      tick = self.tickPlugin,
      evnt = self.handleEvent,
      quit = self.quit
    )
    self.evntHandlers = Namespace()
    self.logInfo(f'Initializing plugin {plugin.key}')
    self.plugin.init()

  def updateLoop(self):
    while not self.quitting:
      try: forceQuit = self.forceQuit.value
      except FileNotFoundError: return
      if forceQuit: break
      incoming = []
      while not self.plgnQueue.empty():
        try: event = self.plgnQueue.get()
        except BrokenPipeError: break
        try: self.evntHandlers[event.what](**event.getArgs())
        except:
          self.quitting = True
          raise

  def quitProgram(self):
    self.evntQueue.put(Event('quit'))

  # Internal event handlers

  def configure(self, data):
    for path, value in data.items():
      try: eval(f'self.plugin.cnf.{path}')
      except AttributeError:
        self.logWarn(f'Config error in {self.plugin.key}: path {path} does not exist')
      if type(value) == str: value = f'"{value}"'
      exec(f'self.plugin.cnf.{path} = {value}')

  def tickPlugin(self):
    try: self.plugin.update()
    except Exception as exc:
      self.logError(f'Error during tick in plugin {self.plugin.key}')
      self.cmndQueue.put(Event('error', exception=exc,
        key=self.plugin.key, type='tick'))
      raise

  def handleEvent(self, event):
    self.evntHandlers[event.key](event)

  def quit(self):
    self.quitting = True
    self.plugin.quit()

  # Methods called by the Plugin

  def addEvtHandler(self, key, method):
    self.evntHandlers[key] = method
    self.cmndQueue.put(Event('addEvtHandler', key=key, plugin=self.plugin.key))

  def pushEvnt(self, event):
    self.evntQueue.put(event)

  def pushTask(self, task):
    self.taskQueue.put(task)


def runPlugin(plugin, forceQuit, plgnQueue, evntQueue, logLock):
  executor = Executor(plugin, forceQuit, plgnQueue, evntQueue, logLock)
  try: executor.updateLoop()
  except EOFError: pass
  except KeyboardInterrupt:
    executor.quitProgram()
