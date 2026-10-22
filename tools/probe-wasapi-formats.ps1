# Read-only WASAPI format probe. It does not initialize or start audio streams.
$ErrorActionPreference = 'Stop'

$source = @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace BridgeCastWasapiProbe
{
    internal enum DataFlow : int { Render = 0, Capture = 1 }

    [StructLayout(LayoutKind.Sequential)]
    internal struct PropertyKey
    {
        public Guid FormatId;
        public uint PropertyId;
    }

    [StructLayout(LayoutKind.Explicit, Size = 16)]
    internal struct PropVariant
    {
        [FieldOffset(0)] public ushort VariantType;
        [FieldOffset(8)] public IntPtr StringPointer;
    }

    [StructLayout(LayoutKind.Sequential, Pack = 2)]
    internal struct WaveFormatEx
    {
        public ushort FormatTag;
        public ushort Channels;
        public uint SamplesPerSecond;
        public uint AverageBytesPerSecond;
        public ushort BlockAlign;
        public ushort BitsPerSample;
        public ushort ExtraSize;
    }

    [StructLayout(LayoutKind.Sequential, Pack = 2)]
    internal struct WaveFormatExtensible
    {
        public WaveFormatEx Format;
        public ushort ValidBitsPerSample;
        public uint ChannelMask;
        public Guid SubFormat;
    }

    [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
    internal class MMDeviceEnumeratorComObject { }

    [ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IMMDeviceEnumerator
    {
        [PreserveSig] int EnumAudioEndpoints(DataFlow flow, uint stateMask, out IMMDeviceCollection devices);
        [PreserveSig] int GetDefaultAudioEndpoint(DataFlow flow, int role, out IMMDevice endpoint);
        [PreserveSig] int GetDevice([MarshalAs(UnmanagedType.LPWStr)] string id, out IMMDevice device);
        [PreserveSig] int RegisterEndpointNotificationCallback(IntPtr client);
        [PreserveSig] int UnregisterEndpointNotificationCallback(IntPtr client);
    }

    [ComImport, Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IMMDeviceCollection
    {
        [PreserveSig] int GetCount(out uint count);
        [PreserveSig] int Item(uint index, out IMMDevice device);
    }

    [ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IMMDevice
    {
        [PreserveSig] int Activate(ref Guid iid, int clsctx, IntPtr activationParams, out IntPtr interfacePointer);
        [PreserveSig] int OpenPropertyStore(int access, out IPropertyStore properties);
        [PreserveSig] int GetId(out IntPtr id);
        [PreserveSig] int GetState(out uint state);
    }

    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IPropertyStore
    {
        [PreserveSig] int GetCount(out uint count);
        [PreserveSig] int GetAt(uint index, out PropertyKey key);
        [PreserveSig] int GetValue(ref PropertyKey key, out PropVariant value);
        [PreserveSig] int SetValue(ref PropertyKey key, ref PropVariant value);
        [PreserveSig] int Commit();
    }

    [ComImport, Guid("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IAudioClient
    {
        [PreserveSig] int Initialize(int shareMode, int streamFlags, long bufferDuration, long periodicity, IntPtr format, IntPtr sessionGuid);
        [PreserveSig] int GetBufferSize(out uint bufferSize);
        [PreserveSig] int GetStreamLatency(out long latency);
        [PreserveSig] int GetCurrentPadding(out uint padding);
        [PreserveSig] int IsFormatSupported(int shareMode, IntPtr format, IntPtr closestMatchFormatPointer);
        [PreserveSig] int GetMixFormat(out IntPtr format);
        [PreserveSig] int GetDevicePeriod(out long defaultPeriod, out long minimumPeriod);
        [PreserveSig] int Start();
        [PreserveSig] int Stop();
        [PreserveSig] int Reset();
        [PreserveSig] int SetEventHandle(IntPtr eventHandle);
        [PreserveSig] int GetService(ref Guid iid, out IntPtr service);
    }

    internal sealed class Candidate
    {
        public string Name;
        public ushort ContainerBits;
        public ushort ValidBits;
        public Guid SubFormat;
    }

    public static class Probe
    {
        private const int ClsCtxAll = 23;
        private const int Shared = 0;
        private const int Exclusive = 1;
        private const int SOk = 0;
        private const int SFalse = 1;
        private static readonly Guid PcmSubFormat = new Guid("00000001-0000-0010-8000-00AA00389B71");
        private static readonly Guid FloatSubFormat = new Guid("00000003-0000-0010-8000-00AA00389B71");

        [DllImport("ole32.dll")]
        private static extern int PropVariantClear(ref PropVariant value);

        private static string FriendlyName(IMMDevice device)
        {
            IPropertyStore store = null;
            PropVariant value = new PropVariant();
            try
            {
                int hr = device.OpenPropertyStore(0, out store);
                if (hr < 0 || store == null) return "<name unavailable>";
                PropertyKey key = new PropertyKey();
                key.FormatId = new Guid("A45C254E-DF1C-4EFD-8020-67D146A850E0");
                key.PropertyId = 14;
                hr = store.GetValue(ref key, out value);
                if (hr == SOk && value.VariantType == 31 && value.StringPointer != IntPtr.Zero)
                    return Marshal.PtrToStringUni(value.StringPointer);
                return "<name unavailable>";
            }
            finally
            {
                PropVariantClear(ref value);
                if (store != null && Marshal.IsComObject(store)) Marshal.ReleaseComObject(store);
            }
        }

        private static string Describe(WaveFormatEx format, ushort validBits, Guid subFormat)
        {
            string encoding = subFormat == FloatSubFormat ? "Float" : subFormat == PcmSubFormat ? "PCM" : "Subtype";
            return String.Format("{0}/{1}ch/valid{2}-in-{3}", encoding, format.Channels, validBits, format.BitsPerSample);
        }

        private static IntPtr BuildFormat(ushort channels, uint rate, Candidate candidate, uint channelMask)
        {
            WaveFormatExtensible value = new WaveFormatExtensible();
            value.Format.FormatTag = 0xFFFE;
            value.Format.Channels = channels;
            value.Format.SamplesPerSecond = rate;
            value.Format.BitsPerSample = candidate.ContainerBits;
            value.Format.BlockAlign = (ushort)(channels * (candidate.ContainerBits / 8));
            value.Format.AverageBytesPerSecond = rate * value.Format.BlockAlign;
            value.Format.ExtraSize = 22;
            value.ValidBitsPerSample = candidate.ValidBits;
            value.ChannelMask = channelMask;
            value.SubFormat = candidate.SubFormat;
            IntPtr pointer = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(WaveFormatExtensible)));
            Marshal.StructureToPtr(value, pointer, false);
            return pointer;
        }

        private static int TestFormat(IAudioClient client, int shareMode, IntPtr format, out WaveFormatEx closest)
        {
            IntPtr slot = IntPtr.Zero;
            IntPtr closestPointer = IntPtr.Zero;
            closest = new WaveFormatEx();
            try
            {
                if (shareMode == Shared)
                {
                    slot = Marshal.AllocHGlobal(IntPtr.Size);
                    Marshal.WriteIntPtr(slot, IntPtr.Zero);
                }
                int hr = client.IsFormatSupported(shareMode, format, slot);
                if (shareMode == Shared && slot != IntPtr.Zero)
                {
                    closestPointer = Marshal.ReadIntPtr(slot);
                    if (closestPointer != IntPtr.Zero)
                        closest = (WaveFormatEx)Marshal.PtrToStructure(closestPointer, typeof(WaveFormatEx));
                }
                return hr;
            }
            finally
            {
                if (closestPointer != IntPtr.Zero) Marshal.FreeCoTaskMem(closestPointer);
                if (slot != IntPtr.Zero) Marshal.FreeHGlobal(slot);
            }
        }

        private static string HResult(int value)
        {
            return String.Format("0x{0:X8}", unchecked((uint)value));
        }

        public static string[] Run()
        {
            List<string> output = new List<string>();
            IMMDeviceEnumerator enumerator = null;
            try
            {
                enumerator = (IMMDeviceEnumerator)new MMDeviceEnumeratorComObject();
                foreach (DataFlow flow in new DataFlow[] { DataFlow.Render, DataFlow.Capture })
                {
                    IMMDeviceCollection devices = null;
                    int hr = enumerator.EnumAudioEndpoints(flow, 1, out devices);
                    if (hr < 0) Marshal.ThrowExceptionForHR(hr);
                    try
                    {
                        uint count;
                        devices.GetCount(out count);
                        for (uint i = 0; i < count; i++)
                        {
                            IMMDevice device = null;
                            IAudioClient client = null;
                            IntPtr clientPointer = IntPtr.Zero;
                            IntPtr mixPointer = IntPtr.Zero;
                            try
                            {
                                hr = devices.Item(i, out device);
                                if (hr < 0) continue;
                                string name = FriendlyName(device);
                                Guid iid = new Guid("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2");
                                hr = device.Activate(ref iid, ClsCtxAll, IntPtr.Zero, out clientPointer);
                                if (hr < 0 || clientPointer == IntPtr.Zero)
                                {
                                    output.Add(String.Format("{0} | {1} | Activate failed {2}", flow, name, HResult(hr)));
                                    continue;
                                }
                                client = (IAudioClient)Marshal.GetObjectForIUnknown(clientPointer);
                                hr = client.GetMixFormat(out mixPointer);
                                if (hr < 0 || mixPointer == IntPtr.Zero)
                                {
                                    output.Add(String.Format("{0} | {1} | GetMixFormat failed {2}", flow, name, HResult(hr)));
                                    continue;
                                }

                                WaveFormatEx mix = (WaveFormatEx)Marshal.PtrToStructure(mixPointer, typeof(WaveFormatEx));
                                ushort validBits = mix.BitsPerSample;
                                uint channelMask = mix.Channels == 2 ? 3u : 0u;
                                Guid subFormat = mix.FormatTag == 3 ? FloatSubFormat : PcmSubFormat;
                                if (mix.FormatTag == 0xFFFE && mix.ExtraSize >= 22)
                                {
                                    WaveFormatExtensible ext = (WaveFormatExtensible)Marshal.PtrToStructure(mixPointer, typeof(WaveFormatExtensible));
                                    validBits = ext.ValidBitsPerSample;
                                    channelMask = ext.ChannelMask;
                                    subFormat = ext.SubFormat;
                                }
                                output.Add(String.Format("{0} | {1} | mix={2}Hz {3} tag=0x{4:X4} mask=0x{5:X8}",
                                    flow, name, mix.SamplesPerSecond, Describe(mix, validBits, subFormat), mix.FormatTag, channelMask));

                                Candidate[] candidates = new Candidate[] {
                                    new Candidate { Name = "PCM16", ContainerBits = 16, ValidBits = 16, SubFormat = PcmSubFormat },
                                    new Candidate { Name = "PCM24-in-24", ContainerBits = 24, ValidBits = 24, SubFormat = PcmSubFormat },
                                    new Candidate { Name = "PCM24-in-32", ContainerBits = 32, ValidBits = 24, SubFormat = PcmSubFormat },
                                    new Candidate { Name = "PCM32", ContainerBits = 32, ValidBits = 32, SubFormat = PcmSubFormat },
                                    new Candidate { Name = "Float32", ContainerBits = 32, ValidBits = 32, SubFormat = FloatSubFormat }
                                };
                                List<string> exclusiveExact = new List<string>();
                                List<string> sharedExact = new List<string>();
                                List<string> sharedClosest = new List<string>();
                                foreach (uint rate in new uint[] { 44100, 48000, 96000 })
                                {
                                    foreach (Candidate candidate in candidates)
                                    {
                                        IntPtr format = BuildFormat(mix.Channels, rate, candidate, channelMask);
                                        try
                                        {
                                            WaveFormatEx closest;
                                            int exclusiveHr = TestFormat(client, Exclusive, format, out closest);
                                            if (exclusiveHr == SOk)
                                                exclusiveExact.Add(String.Format("{0}@{1}", candidate.Name, rate));

                                            int sharedHr = TestFormat(client, Shared, format, out closest);
                                            if (sharedHr == SOk)
                                                sharedExact.Add(String.Format("{0}@{1}", candidate.Name, rate));
                                            else if (sharedHr == SFalse)
                                                sharedClosest.Add(String.Format("{0}@{1}->closest {2}Hz/{3}ch", candidate.Name, rate, closest.SamplesPerSecond, closest.Channels));
                                        }
                                        finally
                                        {
                                            Marshal.FreeHGlobal(format);
                                        }
                                    }
                                }
                                output.Add("  exclusive exact: " + (exclusiveExact.Count == 0 ? "none" : String.Join(", ", exclusiveExact.ToArray())));
                                output.Add("  shared exact: " + (sharedExact.Count == 0 ? "none" : String.Join(", ", sharedExact.ToArray())));
                                output.Add("  shared closest: " + (sharedClosest.Count == 0 ? "none" : String.Join(", ", sharedClosest.ToArray())));
                            }
                            catch (Exception ex)
                            {
                                output.Add(String.Format("{0} | endpoint {1} | probe error: {2}", flow, i, ex.Message));
                            }
                            finally
                            {
                                if (mixPointer != IntPtr.Zero) Marshal.FreeCoTaskMem(mixPointer);
                                if (client != null && Marshal.IsComObject(client)) Marshal.ReleaseComObject(client);
                                if (clientPointer != IntPtr.Zero) Marshal.Release(clientPointer);
                                if (device != null && Marshal.IsComObject(device)) Marshal.ReleaseComObject(device);
                            }
                        }
                    }
                    finally
                    {
                        if (devices != null && Marshal.IsComObject(devices)) Marshal.ReleaseComObject(devices);
                    }
                }
            }
            finally
            {
                if (enumerator != null && Marshal.IsComObject(enumerator)) Marshal.ReleaseComObject(enumerator);
            }
            return output.ToArray();
        }
    }
}
'@

Add-Type -TypeDefinition $source -Language CSharp
[BridgeCastWasapiProbe.Probe]::Run()
