"""Windows Job Object implementation; imported only on Windows.

The primary thread is suspended until assignment, so even immediate grandchildren
inherit the job. No breakaway permission is enabled. All handles are noninheritable.
"""
import ctypes as c
from ctypes import wintypes as w

k32 = c.WinDLL("kernel32", use_last_error=True)


def api(name, restype, *args):
    fn = getattr(k32, name)
    fn.restype, fn.argtypes = restype, args
    return fn


CreateJob = api("CreateJobObjectW", w.HANDLE, c.c_void_p, w.LPCWSTR)
SetInfo = api("SetInformationJobObject", w.BOOL, w.HANDLE, c.c_int, c.c_void_p, w.DWORD)
Assign = api("AssignProcessToJobObject", w.BOOL, w.HANDLE, w.HANDLE)
Terminate = api("TerminateJobObject", w.BOOL, w.HANDLE, w.UINT)
Close = api("CloseHandle", w.BOOL, w.HANDLE)
Snapshot = api("CreateToolhelp32Snapshot", w.HANDLE, w.DWORD, w.DWORD)
First = api("Thread32First", w.BOOL, w.HANDLE, c.c_void_p)
Next = api("Thread32Next", w.BOOL, w.HANDLE, c.c_void_p)
OpenThread = api("OpenThread", w.HANDLE, w.DWORD, w.BOOL, w.DWORD)
Resume = api("ResumeThread", w.DWORD, w.HANDLE)


class Basic(c.Structure):
    _fields_ = [("process_time", c.c_longlong), ("job_time", c.c_longlong),
                ("flags", w.DWORD), ("min_ws", c.c_size_t), ("max_ws", c.c_size_t),
                ("active", w.DWORD), ("affinity", c.c_size_t),
                ("priority", w.DWORD), ("scheduling", w.DWORD)]


class Extended(c.Structure):
    _fields_ = [("basic", Basic), ("io", c.c_ulonglong * 6),
                ("process_mem", c.c_size_t), ("job_mem", c.c_size_t),
                ("peak_process", c.c_size_t), ("peak_job", c.c_size_t)]


class ThreadEntry(c.Structure):
    _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("tid", w.DWORD),
                ("pid", w.DWORD), ("base_priority", w.LONG),
                ("delta_priority", w.LONG), ("flags", w.DWORD)]


def checked(result):
    if not result:
        raise c.WinError(c.get_last_error())
    return result


class Job:
    def __init__(self):
        self.handle = checked(CreateJob(None, None))
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            checked(SetInfo(self.handle, 9, c.byref(info), c.sizeof(info)))
        except BaseException:
            self.close()
            raise

    def attach_and_resume(self, process):
        checked(Assign(self.handle, int(process._handle)))
        snapshot = Snapshot(4, 0)  # TH32CS_SNAPTHREAD
        if snapshot == c.c_void_p(-1).value:
            raise c.WinError(c.get_last_error())
        try:
            entry = ThreadEntry()
            entry.size = c.sizeof(entry)
            more = First(snapshot, c.byref(entry))
            while more:
                if entry.pid == process.pid:
                    thread = checked(OpenThread(2, False, entry.tid))  # THREAD_SUSPEND_RESUME
                    try:
                        if Resume(thread) == 0xFFFFFFFF:
                            raise c.WinError(c.get_last_error())
                    finally:
                        Close(thread)
                    return
                more = Next(snapshot, c.byref(entry))
            raise OSError("cannot find suspended child thread; refusing to start")
        finally:
            Close(snapshot)

    def terminate(self):
        checked(Terminate(self.handle, 1))

    def close(self):
        if self.handle:
            checked(Close(self.handle))
            self.handle = None
