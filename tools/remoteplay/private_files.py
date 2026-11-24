"""Private state files: POSIX modes or an explicit protected Windows DACL."""
import csv
import ctypes as c
from functools import lru_cache
import os
import subprocess


@lru_cache(maxsize=1)
def user_sid():
    result = subprocess.check_output(['whoami', '/user', '/fo', 'csv', '/nh'], text=True)
    return next(csv.reader([result.strip()]))[1]


def protect(path):
    if os.name != 'nt':
        os.chmod(path, 0o600)
        return
    adv = c.WinDLL('advapi32', use_last_error=True)
    kernel = c.WinDLL('kernel32', use_last_error=True)
    sd = c.c_void_p()
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [c.c_wchar_p, c.c_ulong, c.POINTER(c.c_void_p), c.c_void_p]
    adv.SetFileSecurityW.argtypes = [c.c_wchar_p, c.c_ulong, c.c_void_p]
    kernel.LocalFree.argtypes = [c.c_void_p]
    sddl = f'D:P(A;;FA;;;{user_sid()})(A;;FA;;;SY)(A;;FA;;;BA)'
    if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, c.byref(sd), None):
        raise c.WinError(c.get_last_error())
    try:
        if not adv.SetFileSecurityW(str(path), 0x80000004, sd):
            raise c.WinError(c.get_last_error())
    finally:
        kernel.LocalFree(sd)


def assert_private(test, path):
    if os.name != 'nt':
        test.assertEqual(path.stat().st_mode & 0o777, 0o600)
        return
    # Inspect effective ACE identities and inheritance, independently of the writer.
    env = os.environ.copy()
    env.pop('PSModulePath', None)
    env['RP_ACL_TEST_PATH'] = str(path)
    script = "(Get-Acl -LiteralPath $env:RP_ACL_TEST_PATH).Access | ForEach-Object { $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value + ':' + $_.IsInherited }"
    lines = subprocess.check_output(['pwsh', '-NoProfile', '-Command', script], env=env, text=True).splitlines()
    test.assertEqual(set(lines), {user_sid()+':False', 'S-1-5-18:False', 'S-1-5-32-544:False'})
