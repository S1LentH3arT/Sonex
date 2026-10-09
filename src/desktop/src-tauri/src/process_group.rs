#[cfg(windows)]
pub struct ProcessGroup(windows_sys::Win32::Foundation::HANDLE);
#[cfg(windows)]
unsafe impl Send for ProcessGroup {}

#[cfg(windows)]
impl ProcessGroup {
    pub fn attach(pid: u32) -> std::io::Result<Self> {
        use windows_sys::Win32::{Foundation::CloseHandle, System::{JobObjects::*, Threading::*}};
        unsafe {
            let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            if job.is_null() { return Err(std::io::Error::last_os_error()); }
            let group = Self(job);
            let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits as *const _ as *const _, std::mem::size_of_val(&limits) as u32) == 0 {
                return Err(std::io::Error::last_os_error());
            }
            let process = OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, 0, pid);
            if process.is_null() { return Err(std::io::Error::last_os_error()); }
            let result = AssignProcessToJobObject(job, process);
            let error = std::io::Error::last_os_error();
            CloseHandle(process);
            if result == 0 { return Err(error); }
            Ok(group)
        }
    }
}
#[cfg(windows)]
impl Drop for ProcessGroup {
    fn drop(&mut self) { unsafe { windows_sys::Win32::Foundation::CloseHandle(self.0); } }
}

#[cfg(not(windows))]
pub struct ProcessGroup;
#[cfg(not(windows))]
impl ProcessGroup {
    pub fn attach(_: u32) -> std::io::Result<Self> { Ok(Self) }
}
