import sys
import os

# Add the parent directory to the python path so we can import engine
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import Engine
# Note: In the actual benchmark repo, these imports might look slightly different depending on their structure.
# The prompt assumes: from schema import Event, IncidentSignal, Context; and from adapter import Adapter
try:
    from schema import Event, IncidentSignal, Context
    from adapter import Adapter
except ImportError:
    # Fallback placeholders in case the hackathon hasn't provided the schema.py locally yet
    class Adapter:
        pass
    Event = dict
    IncidentSignal = dict
    Context = dict

class EngineAdapter(Adapter):
    def __init__(self):
        self.engine = Engine()
    
    def ingest(self, events):
        """Call our Engine's ingest method"""
        self.engine.ingest(events)
    
    def reconstruct_context(self, signal, mode='fast'):
        """Call our Engine's ContextBuilder to reconstruct the incident context"""
        # We pass the signal directly to the context builder
        return self.engine.context_builder.build_context(signal)
    
    def close(self):
        """Cleanup any resources if needed"""
        pass
