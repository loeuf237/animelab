package com.animan.extensions;
import android.os.ParcelFileDescriptor;
interface IExtensionHttp {
    ParcelFileDescriptor request(String payload);
}
