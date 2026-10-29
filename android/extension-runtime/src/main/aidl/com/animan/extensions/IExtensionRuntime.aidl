package com.animan.extensions;
import com.animan.extensions.IExtensionHttp;
interface IExtensionRuntime {
    void attachGateway(IExtensionHttp gateway);
    String discover();
    String invoke(String payload);
    void cancel(String operation);
    void terminate();
}
