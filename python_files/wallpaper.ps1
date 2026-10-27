# Меняет обои сразу на всех виртуальных рабочих столах Windows 11.
# Активация COM через .NET COM-интероп (Activator.CreateInstance), как в
# MScholtes/VirtualDesktop. Ничего не пишется на диск: C# компилируется
# в памяти через Add-Type.
param(
    [Parameter(Mandatory = $true)][string]$Path
)
$ErrorActionPreference = 'Stop'

$build = [System.Environment]::OSVersion.Version.Build
if ($build -lt 22621) {
    Write-Output "ERR:wallpaper:only Windows 11 22H2+"
    exit 1
}

$prefix = @'
using System;
using System.Runtime.InteropServices;

public static class SetAllWallpapers {
    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("6D5140C1-7436-11CE-8034-00AA006009FA")]
    interface IServiceProvider10 { [return: MarshalAs(UnmanagedType.IUnknown)] object QueryService(ref Guid service, ref Guid riid); }

    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("53F5CA0B-158F-4124-900C-057158060B27")]
    interface IVirtualDesktopManagerInternal {
        int GetCount();
        void MoveViewToDesktop(object view, object desktop);
        bool CanViewMoveDesktops(object view);
        object GetCurrentDesktop();
        void GetDesktops(out object desktops);
        int GetAdjacentDesktop(object from, int direction, out object desktop);
        void SwitchDesktop(object desktop);
'@

# В Windows 11 24H2 (build >= 26100) в интерфейс добавили метод, поэтому
# UpdateWallpaperPathForAllDesktops сместился в vtable.
$extra24h2 = @'
        void SwitchDesktopAndMoveForegroundView(object desktop);
'@

$suffix = @'
        object CreateDesktop();
        void MoveDesktop(object desktop, int nIndex);
        void RemoveDesktop(object desktop, object fallback);
        object FindDesktop(ref Guid desktopid);
        void GetDesktopSwitchIncludeExcludeViews(object desktop, out object a, out object b);
        void SetDesktopName(object desktop, [MarshalAs(UnmanagedType.HString)] string name);
        void SetDesktopWallpaper(object desktop, [MarshalAs(UnmanagedType.HString)] string path);
        void UpdateWallpaperPathForAllDesktops([MarshalAs(UnmanagedType.HString)] string path);
    }

    public static string Apply(string path) {
        Guid CLSID_ImmersiveShell = new Guid("C2F03A33-21F5-47FA-B4BB-156362A2F239");
        Guid CLSID_VDMInternal = new Guid("C5E0CDCA-7B6E-41B2-9FC4-D93975CC467B");
        var shell = (IServiceProvider10)Activator.CreateInstance(Type.GetTypeFromCLSID(CLSID_ImmersiveShell));
        var mgr = (IVirtualDesktopManagerInternal)shell.QueryService(ref CLSID_VDMInternal, typeof(IVirtualDesktopManagerInternal).GUID);
        mgr.UpdateWallpaperPathForAllDesktops(path);
        return "";
    }
}
'@

$csharp = $prefix
if ($build -ge 26100) {
    $csharp += $extra24h2
}
$csharp += $suffix

Add-Type -TypeDefinition $csharp

try {
    [SetAllWallpapers]::Apply($Path)
} catch {
    Write-Output ("ERR:wallpaper:" + $_.Exception.Message)
    exit 1
}
Write-Output "OK"
exit 0