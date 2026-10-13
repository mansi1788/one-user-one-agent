"""Per-decision call budgets; logical repository and provider operations are counted."""
import threading
import time

class BudgetExceeded(RuntimeError):
    pass

class Budget:
    def __init__(self,max_model_calls=8,max_tool_calls=20,max_seconds=60,clock=time.monotonic):
        if min(max_model_calls,max_tool_calls,max_seconds)<0:
            raise ValueError("Budgets must be nonnegative")
        self.limits={"model":max_model_calls,"tool":max_tool_calls}
        self.counts={"model":0,"tool":0}
        self.log=[]
        self.clock,self.started,self.max_seconds=clock,clock(),max_seconds
        self.lock=threading.Lock()

    def charge(self,kind,name):
        with self.lock:
            denied=self.counts[kind]>=self.limits[kind] or self.clock()-self.started>=self.max_seconds
            entry={"kind":kind,"name":name,"status":"denied" if denied else "counted"}
            self.log.append(entry)
            if denied:
                raise BudgetExceeded(f"{kind} call or time budget exceeded before {name}")
            self.counts[kind]+=1
            return entry

    def call(self,kind,name,function,*args,**kwargs):
        entry=self.charge(kind,name)
        start=self.clock()
        try:
            if getattr(self,"before_call",None):
                self.before_call(kind,name,entry)
            result=function(*args,**kwargs)
            if self.clock()-self.started>=self.max_seconds:
                raise BudgetExceeded("Decision time budget exceeded")
            entry["status"]="completed"
            return result
        except Exception as exc:
            entry.update(status="failed",error=type(exc).__name__)
            raise
        finally:
            entry["elapsed_seconds"]=max(0,self.clock()-start)

    def snapshot(self):
        return {"limits":dict(self.limits),"counts":dict(self.counts),"calls":[dict(e) for e in self.log],
                "elapsed_seconds":max(0,self.clock()-self.started)}
