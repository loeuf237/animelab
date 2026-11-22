/* AnimeLab Seanime Extension Runtime Shim (ES2022)
 * Shared between desktop/Docker MiniRacer V8 and Android offscreen WebView.
 */
(function (global) {
  'use strict';

  var MAX_LOGS = 200;
  var _logs = [];

  function pushLog(level, args) {
    if (_logs.length >= MAX_LOGS) return;
    var parts = [];
    for (var i = 0; i < args.length; i++) {
      var v = args[i];
      if (typeof v === 'string') {
        parts.push(v);
      } else {
        try {
          parts.push(JSON.stringify(v));
        } catch (_e) {
          parts.push(String(v));
        }
      }
    }
    _logs.push('[' + level + '] ' + parts.join(' '));
  }

  global.console = {
    log: function () { pushLog('log', arguments); },
    info: function () { pushLog('info', arguments); },
    warn: function () { pushLog('warn', arguments); },
    error: function () { pushLog('error', arguments); },
    debug: function () { pushLog('debug', arguments); },
  };

  // --- UTF-8 / Base64 / Binary helpers ---
  function utf8Encode(str) {
    str = String(str == null ? '' : str);
    var out = [];
    for (var i = 0; i < str.length; i++) {
      var c = str.charCodeAt(i);
      if (c < 0x80) {
        out.push(c);
      } else if (c < 0x800) {
        out.push(0xc0 | (c >> 6), 0x80 | (c & 0x3f));
      } else if (c >= 0xd800 && c <= 0xdbff && i + 1 < str.length) {
        var c2 = str.charCodeAt(++i);
        var cp = 0x10000 + (((c & 0x3ff) << 10) | (c2 & 0x3ff));
        out.push(
          0xf0 | (cp >> 18),
          0x80 | ((cp >> 12) & 0x3f),
          0x80 | ((cp >> 6) & 0x3f),
          0x80 | (cp & 0x3f)
        );
      } else {
        out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 0x3f), 0x80 | (c & 0x3f));
      }
    }
    return new Uint8Array(out);
  }

  function utf8Decode(bytes) {
    bytes = asBytes(bytes);
    var out = '';
    var i = 0;
    while (i < bytes.length) {
      var b0 = bytes[i++];
      if (b0 < 0x80) {
        out += String.fromCharCode(b0);
      } else if ((b0 & 0xe0) === 0xc0 && i < bytes.length) {
        var b1 = bytes[i++] & 0x3f;
        out += String.fromCharCode(((b0 & 0x1f) << 6) | b1);
      } else if ((b0 & 0xf0) === 0xe0 && i + 1 < bytes.length) {
        var b1e = bytes[i++] & 0x3f;
        var b2e = bytes[i++] & 0x3f;
        out += String.fromCharCode(((b0 & 0x0f) << 12) | (b1e << 6) | b2e);
      } else if ((b0 & 0xf8) === 0xf0 && i + 2 < bytes.length) {
        var b1f = bytes[i++] & 0x3f;
        var b2f = bytes[i++] & 0x3f;
        var b3f = bytes[i++] & 0x3f;
        var cp = ((b0 & 0x07) << 18) | (b1f << 12) | (b2f << 6) | b3f;
        if (cp > 0xffff) {
          cp -= 0x10000;
          out += String.fromCharCode(0xd800 + (cp >> 10), 0xdc00 + (cp & 0x3ff));
        } else {
          out += String.fromCharCode(cp);
        }
      } else {
        out += '\ufffd';
      }
    }
    return out;
  }

  var B64_ALPHA = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  var B64_LOOKUP = (function () {
    var m = new Int16Array(256);
    m.fill(-1);
    for (var i = 0; i < B64_ALPHA.length; i++) {
      m[B64_ALPHA.charCodeAt(i)] = i;
    }
    m['-'.charCodeAt(0)] = 62;
    m['_'.charCodeAt(0)] = 63;
    return m;
  })();

  function bytesToBase64(bytes) {
    bytes = asBytes(bytes);
    var out = '';
    for (var i = 0; i < bytes.length; i += 3) {
      var b0 = bytes[i];
      var has1 = i + 1 < bytes.length;
      var has2 = i + 2 < bytes.length;
      var b1 = has1 ? bytes[i + 1] : 0;
      var b2 = has2 ? bytes[i + 2] : 0;
      out += B64_ALPHA[b0 >> 2];
      out += B64_ALPHA[((b0 & 3) << 4) | (b1 >> 4)];
      out += has1 ? B64_ALPHA[((b1 & 15) << 2) | (b2 >> 6)] : '=';
      out += has2 ? B64_ALPHA[b2 & 63] : '=';
    }
    return out;
  }

  function base64ToBytes(str) {
    str = String(str == null ? '' : str).replace(/\s+/g, '').replace(/=+$/, '');
    var out = [];
    for (var i = 0; i < str.length; i += 4) {
      var c0 = B64_LOOKUP[str.charCodeAt(i) & 255];
      var c1 = i + 1 < str.length ? B64_LOOKUP[str.charCodeAt(i + 1) & 255] : -1;
      var c2 = i + 2 < str.length ? B64_LOOKUP[str.charCodeAt(i + 2) & 255] : -1;
      var c3 = i + 3 < str.length ? B64_LOOKUP[str.charCodeAt(i + 3) & 255] : -1;
      if (c0 < 0 || c1 < 0) break;
      out.push((c0 << 2) | (c1 >> 4));
      if (c2 >= 0) {
        out.push(((c1 & 15) << 4) | (c2 >> 2));
        if (c3 >= 0) out.push(((c2 & 3) << 6) | c3);
      }
    }
    return new Uint8Array(out);
  }

  function asBytes(val) {
    if (val == null) return new Uint8Array(0);
    if (val instanceof Uint8Array) return val;
    if (val._bytes instanceof Uint8Array) return val._bytes;
    if (val instanceof ArrayBuffer) return new Uint8Array(val);
    if (ArrayBuffer.isView(val)) return new Uint8Array(val.buffer, val.byteOffset, val.byteLength);
    if (Array.isArray(val)) return new Uint8Array(val);
    if (typeof val === 'string') return utf8Encode(val);
    try {
      return utf8Encode(JSON.stringify(val));
    } catch (_e) {
      return utf8Encode(String(val));
    }
  }

  if (typeof global.TextEncoder === 'undefined') {
    global.TextEncoder = function TextEncoder() {};
    global.TextEncoder.prototype.encode = function (s) { return utf8Encode(s); };
  }
  if (typeof global.TextDecoder === 'undefined') {
    global.TextDecoder = function TextDecoder() {};
    global.TextDecoder.prototype.decode = function (b) { return utf8Decode(b || new Uint8Array(0)); };
  }
  if (typeof global.atob === 'undefined') {
    global.atob = function (b64) {
      var bytes = base64ToBytes(b64);
      var out = '';
      for (var i = 0; i < bytes.length; i++) out += String.fromCharCode(bytes[i]);
      return out;
    };
  }
  if (typeof global.btoa === 'undefined') {
    global.btoa = function (bin) {
      bin = String(bin == null ? '' : bin);
      var bytes = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i) & 0xff;
      return bytesToBase64(bytes);
    };
  }

  if (typeof global.Buffer === 'undefined') {
    var BufferShim = {
      from: function (input, enc) {
        if (input instanceof Uint8Array) return new Uint8Array(input);
        if (input instanceof ArrayBuffer) return new Uint8Array(input);
        if (Array.isArray(input)) return new Uint8Array(input);
        var s = String(input == null ? '' : input);
        var mode = String(enc || 'utf8').toLowerCase();
        if (mode === 'base64' || mode === 'base64url') return base64ToBytes(s);
        if (mode === 'hex') return hexToBytes(s);
        if (mode === 'latin1' || mode === 'binary') {
          var arr = new Uint8Array(s.length);
          for (var i = 0; i < s.length; i++) arr[i] = s.charCodeAt(i) & 0xff;
          return arr;
        }
        return utf8Encode(s);
      },
      alloc: function (len, fill) {
        var b = new Uint8Array(len || 0);
        if (fill) b.fill(Number(fill) & 0xff);
        return b;
      },
      concat: function (list) {
        var total = 0;
        for (var i = 0; i < list.length; i++) total += list[i].length;
        var out = new Uint8Array(total);
        var off = 0;
        for (var j = 0; j < list.length; j++) {
          out.set(asBytes(list[j]), off);
          off += list[j].length;
        }
        return out;
      },
      isBuffer: function (v) { return v instanceof Uint8Array; },
    };
    Uint8Array.prototype.toString = (function (origToString) {
      return function (enc) {
        if (!enc) return origToString.call(this);
        var mode = String(enc).toLowerCase();
        if (mode === 'base64') return bytesToBase64(this);
        if (mode === 'base64url') return bytesToBase64(this).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
        if (mode === 'hex') return bytesToHex(this);
        if (mode === 'latin1' || mode === 'binary') {
          var s = '';
          for (var i = 0; i < this.length; i++) s += String.fromCharCode(this[i]);
          return s;
        }
        return utf8Decode(this);
      };
    })(Uint8Array.prototype.toString);
    global.Buffer = BufferShim;
  }

  // --- URLSearchParams / URL polyfill if absent (bare V8) ---
  if (typeof global.URLSearchParams === 'undefined') {
    global.URLSearchParams = function URLSearchParams(init) {
      this._entries = [];
      if (typeof init === 'string') {
        var s = init.charAt(0) === '?' ? init.slice(1) : init;
        if (s) {
          var pairs = s.split('&');
          for (var i = 0; i < pairs.length; i++) {
            var part = pairs[i];
            if (!part) continue;
            var eq = part.indexOf('=');
            var k = eq >= 0 ? part.slice(0, eq) : part;
            var v = eq >= 0 ? part.slice(eq + 1) : '';
            this._entries.push([decodeURIComponent(k.replace(/\+/g, ' ')), decodeURIComponent(v.replace(/\+/g, ' '))]);
          }
        }
      } else if (Array.isArray(init)) {
        for (var j = 0; j < init.length; j++) {
          this._entries.push([String(init[j][0]), String(init[j][1])]);
        }
      } else if (init && typeof init === 'object') {
        var keys = Object.keys(init);
        for (var q = 0; q < keys.length; q++) {
          this._entries.push([keys[q], String(init[keys[q]])]);
        }
      }
    };
    URLSearchParams.prototype.append = function (k, v) { this._entries.push([String(k), String(v)]); };
    URLSearchParams.prototype.set = function (k, v) {
      k = String(k);
      var out = [];
      var placed = false;
      for (var i = 0; i < this._entries.length; i++) {
        if (this._entries[i][0] === k) {
          if (!placed) { out.push([k, String(v)]); placed = true; }
        } else {
          out.push(this._entries[i]);
        }
      }
      if (!placed) out.push([k, String(v)]);
      this._entries = out;
    };
    URLSearchParams.prototype.get = function (k) {
      k = String(k);
      for (var i = 0; i < this._entries.length; i++) {
        if (this._entries[i][0] === k) return this._entries[i][1];
      }
      return null;
    };
    URLSearchParams.prototype.getAll = function (k) {
      k = String(k);
      var res = [];
      for (var i = 0; i < this._entries.length; i++) {
        if (this._entries[i][0] === k) res.push(this._entries[i][1]);
      }
      return res;
    };
    URLSearchParams.prototype.has = function (k) { return this.get(k) !== null; };
    URLSearchParams.prototype.delete = function (k) {
      k = String(k);
      this._entries = this._entries.filter(function (e) { return e[0] !== k; });
    };
    URLSearchParams.prototype.entries = function () { return this._entries.slice()[Symbol.iterator](); };
    URLSearchParams.prototype[Symbol.iterator] = URLSearchParams.prototype.entries;
    URLSearchParams.prototype.toString = function () {
      return this._entries.map(function (e) {
        return encodeURIComponent(e[0]) + '=' + encodeURIComponent(e[1]);
      }).join('&');
    };
  }

  if (typeof global.URL === 'undefined') {
    global.URL = function URL(urlStr, baseStr) {
      var raw = String(urlStr || '').trim();
      if (baseStr && !/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(raw)) {
        var b = new URL(String(baseStr));
        if (raw.startsWith('//')) raw = b.protocol + raw;
        else if (raw.startsWith('/')) raw = b.origin + raw;
        else if (raw.startsWith('?')) raw = b.origin + b.pathname + raw;
        else if (raw.startsWith('#')) raw = b.origin + b.pathname + b.search + raw;
        else {
          var dir = b.pathname.replace(/\/[^/]*$/, '/');
          raw = b.origin + dir + raw;
        }
      }
      var m = raw.match(/^([a-zA-Z][a-zA-Z0-9+.-]*:)(\/\/([^/?#]*))?([^?#]*)(\?[^#]*)?(#.*)?$/);
      if (!m) throw new TypeError('Invalid URL: ' + raw);
      this.protocol = m[1].toLowerCase();
      var authHost = m[3] || '';
      var atIdx = authHost.lastIndexOf('@');
      var hostPort = atIdx >= 0 ? authHost.slice(atIdx + 1) : authHost;
      var colonIdx = hostPort.lastIndexOf(':');
      if (colonIdx >= 0 && !hostPort.endsWith(']')) {
        this.hostname = hostPort.slice(0, colonIdx).toLowerCase();
        this.port = hostPort.slice(colonIdx + 1);
      } else {
        this.hostname = hostPort.toLowerCase();
        this.port = '';
      }
      this.host = this.port ? this.hostname + ':' + this.port : this.hostname;
      this.origin = this.protocol + '//' + this.host;
      this.pathname = m[4] || '/';
      this.search = m[5] || '';
      this.hash = m[6] || '';
      this.searchParams = new global.URLSearchParams(this.search);
      this.href = this.origin + this.pathname + this.search + this.hash;
    };
    URL.prototype.toString = function () {
      var q = this.searchParams.toString();
      var search = q ? '?' + q : '';
      return this.origin + this.pathname + search + this.hash;
    };
  }

  // --- FormData ---
  global.FormData = function FormData() {
    this.__seanimeFormData = true;
    this._fields = [];
    this._values = Object.create(null);
  };
  global.FormData.prototype.append = function (name, value) {
    var k = String(name).trim();
    var v = String(value == null ? '' : value);
    this._fields.push([k, v]);
    if (!this._values[k]) this._values[k] = [];
    this._values[k].push(v);
  };
  global.FormData.prototype.set = function (name, value) {
    var k = String(name).trim();
    var v = String(value == null ? '' : value);
    this._fields = this._fields.filter(function (p) { return p[0] !== k; });
    this._fields.push([k, v]);
    this._values[k] = [v];
  };
  global.FormData.prototype.delete = function (name) {
    var k = String(name).trim();
    delete this._values[k];
    this._fields = this._fields.filter(function (p) { return p[0] !== k; });
  };
  global.FormData.prototype.get = function (name) {
    var arr = this._values[String(name).trim()];
    return arr && arr.length ? arr[0] : undefined;
  };
  global.FormData.prototype.getAll = function (name) {
    return (this._values[String(name).trim()] || []).slice();
  };
  global.FormData.prototype.has = function (name) {
    return Object.prototype.hasOwnProperty.call(this._values, String(name).trim());
  };
  global.FormData.prototype.keys = function () { return Object.keys(this._values); };
  global.FormData.prototype.values = function () {
    return this._fields.map(function (p) { return p[1]; });
  };
  global.FormData.prototype.entries = function () { return this._fields.slice(); };

  // --- Seanime utility globals ---
  global.$isOffline = function () { return false; };
  global.$toBytes = function (val) { return asBytes(val); };
  global.$toString = function (val) {
    if (typeof val === 'string') return val;
    if (val instanceof Uint8Array || val instanceof ArrayBuffer || val?._bytes instanceof Uint8Array) {
      return utf8Decode(asBytes(val));
    }
    if (val == null) return '';
    if (typeof val === 'object') {
      try { return JSON.stringify(val); } catch (_e) {}
    }
    return String(val);
  };
  global.$toError = function (val) {
    return val instanceof Error ? val : new Error(String(val));
  };
  global.$sleep = function (ms) {
    var capped = Math.min(Math.max(0, Number(ms) || 0), 5000);
    if (capped <= 0) return;
    if (typeof global.__animelabSeanimeSleepSync === 'function') {
      global.__animelabSeanimeSleepSync(capped);
      return;
    }
    try {
      if (typeof SharedArrayBuffer !== 'undefined' && typeof Atomics !== 'undefined') {
        Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, capped);
        return;
      }
    } catch (_e) {}
    var end = Date.now() + Math.min(capped, 1500);
    while (Date.now() < end) {}
  };

  var _userConfig = {};
  var _configDefaults = {};
  global.$getUserPreference = function (key) {
    key = String(key || '');
    if (Object.prototype.hasOwnProperty.call(_userConfig, key) && _userConfig[key] !== '') {
      return _userConfig[key];
    }
    if (Object.prototype.hasOwnProperty.call(_configDefaults, key) && _configDefaults[key] !== '') {
      return _configDefaults[key];
    }
    return undefined;
  };

  var _storeData = Object.create(null);
  function deepClone(v) {
    if (v == null || typeof v !== 'object') return v;
    try { return JSON.parse(JSON.stringify(v)); } catch (_e) { return v; }
  }
  global.$store = {
    get: function (k) { return deepClone(_storeData[String(k)]); },
    getUnsafe: function (k) { return _storeData[String(k)]; },
    set: function (k, v) { _storeData[String(k)] = deepClone(v); },
    has: function (k) { return Object.prototype.hasOwnProperty.call(_storeData, String(k)); },
    remove: function (k) { delete _storeData[String(k)]; },
    removeAll: function () { _storeData = Object.create(null); },
    length: function () { return Object.keys(_storeData).length; },
    getAll: function () { return deepClone(_storeData); },
    getAllUnsafe: function () { return _storeData; },
    getOrSet: function (k, fn) {
      k = String(k);
      if (!Object.prototype.hasOwnProperty.call(_storeData, k) && typeof fn === 'function') {
        _storeData[k] = deepClone(fn());
      }
      return deepClone(_storeData[k]);
    },
    setIfLessThanLimit: function (k, v, limit) {
      if (Object.keys(_storeData).length >= limit) return false;
      _storeData[String(k)] = deepClone(v);
      return true;
    },
    values: function () {
      var out = [];
      var ks = Object.keys(_storeData);
      for (var i = 0; i < ks.length; i++) out.push(deepClone(_storeData[ks[i]]));
      return out;
    },
    valuesUnsafe: function () {
      var out = [];
      var ks = Object.keys(_storeData);
      for (var i = 0; i < ks.length; i++) out.push(_storeData[ks[i]]);
      return out;
    },
    marshalJSON: function () { return JSON.stringify(_storeData); },
    unmarshalJSON: function (s) {
      _storeData = Object.assign(Object.create(null), JSON.parse(String(s || '{}')) || {});
    },
    reset: function (obj) {
      _storeData = Object.assign(Object.create(null), obj && typeof obj === 'object' ? deepClone(obj) : {});
    },
    watch: function () { return function () {}; },
  };

  // --- CryptoJS (AES-128/192/256 CBC/ECB/CTR + MD5 + SHA1 + SHA256 + Encoders) ---
  function bytesToHex(bytes) {
    bytes = asBytes(bytes);
    var out = '';
    for (var i = 0; i < bytes.length; i++) {
      var h = bytes[i].toString(16);
      out += h.length < 2 ? '0' + h : h;
    }
    return out;
  }

  function hexToBytes(hex) {
    hex = String(hex == null ? '' : hex).replace(/\s+/g, '');
    if (hex.length % 2 !== 0) hex = '0' + hex;
    var out = new Uint8Array(hex.length / 2);
    for (var i = 0; i < out.length; i++) {
      out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16) || 0;
    }
    return out;
  }

  function WordArray(bytes, ivBytes) {
    this._bytes = asBytes(bytes);
    this.sigBytes = this._bytes.length;
    this.iv = ivBytes ? asBytes(ivBytes) : new Uint8Array(0);
    var words = [];
    for (var i = 0; i < this._bytes.length; i += 4) {
      words.push(
        ((this._bytes[i] || 0) << 24) |
          ((this._bytes[i + 1] || 0) << 16) |
          ((this._bytes[i + 2] || 0) << 8) |
          (this._bytes[i + 3] || 0)
      );
    }
    this.words = words;
  }
  WordArray.prototype.toString = function (encoder) {
    if (!encoder) return bytesToBase64(this._bytes);
    if (typeof encoder.stringify === 'function') return encoder.stringify(this);
    return utf8Decode(this._bytes);
  };

  var _Enc = {
    Utf8: {
      parse: function (s) { return new WordArray(utf8Encode(s)); },
      stringify: function (w) { return utf8Decode(asBytes(w)); },
    },
    Base64: {
      parse: function (s) { return new WordArray(base64ToBytes(s)); },
      stringify: function (w) { return bytesToBase64(asBytes(w)); },
    },
    Hex: {
      parse: function (s) { return new WordArray(hexToBytes(s)); },
      stringify: function (w) { return bytesToHex(asBytes(w)); },
    },
    Latin1: {
      parse: function (s) {
        s = String(s == null ? '' : s);
        var b = new Uint8Array(s.length);
        for (var i = 0; i < s.length; i++) b[i] = s.charCodeAt(i) & 0xff;
        return new WordArray(b);
      },
      stringify: function (w) {
        var b = asBytes(w);
        var out = '';
        for (var i = 0; i < b.length; i++) out += String.fromCharCode(b[i]);
        return out;
      },
    },
    Utf16: {
      parse: function (s) {
        s = String(s == null ? '' : s);
        var b = new Uint8Array(s.length * 2);
        for (var i = 0; i < s.length; i++) {
          var c = s.charCodeAt(i);
          b[i * 2] = (c >> 8) & 0xff;
          b[i * 2 + 1] = c & 0xff;
        }
        return new WordArray(b);
      },
      stringify: function (w) {
        var b = asBytes(w);
        var out = '';
        for (var i = 0; i + 1 < b.length; i += 2) out += String.fromCharCode((b[i] << 8) | b[i + 1]);
        return out;
      },
    },
    Utf16LE: {
      parse: function (s) {
        s = String(s == null ? '' : s);
        var b = new Uint8Array(s.length * 2);
        for (var i = 0; i < s.length; i++) {
          var c = s.charCodeAt(i);
          b[i * 2] = c & 0xff;
          b[i * 2 + 1] = (c >> 8) & 0xff;
        }
        return new WordArray(b);
      },
      stringify: function (w) {
        var b = asBytes(w);
        var out = '';
        for (var i = 0; i + 1 < b.length; i += 2) out += String.fromCharCode(b[i] | (b[i + 1] << 8));
        return out;
      },
    },
  };

  // SHA-256
  var SHA256_K = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ]);
  function rotr32(v, n) { return (v >>> n) | (v << (32 - n)); }
  function sha256Bytes(msg) {
    msg = asBytes(msg);
    var bitLen = msg.length * 8;
    var padLen = ((msg.length + 9 + 63) >> 6) << 6;
    var buf = new Uint8Array(padLen);
    buf.set(msg);
    buf[msg.length] = 0x80;
    var hi = Math.floor(bitLen / 0x100000000);
    var lo = bitLen >>> 0;
    buf[padLen - 8] = (hi >>> 24) & 0xff;
    buf[padLen - 7] = (hi >>> 16) & 0xff;
    buf[padLen - 6] = (hi >>> 8) & 0xff;
    buf[padLen - 5] = hi & 0xff;
    buf[padLen - 4] = (lo >>> 24) & 0xff;
    buf[padLen - 3] = (lo >>> 16) & 0xff;
    buf[padLen - 2] = (lo >>> 8) & 0xff;
    buf[padLen - 1] = lo & 0xff;
    var H = new Uint32Array([
      0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
      0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
    ]);
    var W = new Uint32Array(64);
    for (var off = 0; off < padLen; off += 64) {
      for (var t = 0; t < 16; t++) {
        var j = off + t * 4;
        W[t] = ((buf[j] << 24) | (buf[j + 1] << 16) | (buf[j + 2] << 8) | buf[j + 3]) >>> 0;
      }
      for (var t2 = 16; t2 < 64; t2++) {
        var s0 = rotr32(W[t2 - 15], 7) ^ rotr32(W[t2 - 15], 18) ^ (W[t2 - 15] >>> 3);
        var s1 = rotr32(W[t2 - 2], 17) ^ rotr32(W[t2 - 2], 19) ^ (W[t2 - 2] >>> 10);
        W[t2] = (W[t2 - 16] + s0 + W[t2 - 7] + s1) >>> 0;
      }
      var a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7];
      for (var k = 0; k < 64; k++) {
        var S1 = rotr32(e, 6) ^ rotr32(e, 11) ^ rotr32(e, 25);
        var ch = (e & f) ^ (~e & g);
        var t1 = (h + S1 + ch + SHA256_K[k] + W[k]) >>> 0;
        var S0 = rotr32(a, 2) ^ rotr32(a, 13) ^ rotr32(a, 22);
        var maj = (a & b) ^ (a & c) ^ (b & c);
        var t2v = (S0 + maj) >>> 0;
        h = g; g = f; f = e; e = (d + t1) >>> 0;
        d = c; c = b; b = a; a = (t1 + t2v) >>> 0;
      }
      H[0] = (H[0] + a) >>> 0; H[1] = (H[1] + b) >>> 0; H[2] = (H[2] + c) >>> 0; H[3] = (H[3] + d) >>> 0;
      H[4] = (H[4] + e) >>> 0; H[5] = (H[5] + f) >>> 0; H[6] = (H[6] + g) >>> 0; H[7] = (H[7] + h) >>> 0;
    }
    var out = new Uint8Array(32);
    for (var z = 0; z < 8; z++) {
      out[z * 4] = (H[z] >>> 24) & 0xff;
      out[z * 4 + 1] = (H[z] >>> 16) & 0xff;
      out[z * 4 + 2] = (H[z] >>> 8) & 0xff;
      out[z * 4 + 3] = H[z] & 0xff;
    }
    return out;
  }

  // MD5 (RFC 1321 - used for OpenSSL EVP_BytesToKey & CryptoJS.MD5)
  var MD5_S = [
    7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
    5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
    4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
    6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
  ];
  var MD5_K = (function () {
    var arr = new Uint32Array(64);
    for (var i = 0; i < 64; i++) arr[i] = Math.floor(Math.abs(Math.sin(i + 1)) * 0x100000000) >>> 0;
    return arr;
  })();
  function md5Bytes(msg) {
    msg = asBytes(msg);
    var bitLen = msg.length * 8;
    var padLen = ((msg.length + 9 + 63) >> 6) << 6;
    var buf = new Uint8Array(padLen);
    buf.set(msg);
    buf[msg.length] = 0x80;
    var lo = bitLen >>> 0;
    var hi = Math.floor(bitLen / 0x100000000) >>> 0;
    buf[padLen - 8] = lo & 0xff; buf[padLen - 7] = (lo >>> 8) & 0xff;
    buf[padLen - 6] = (lo >>> 16) & 0xff; buf[padLen - 5] = (lo >>> 24) & 0xff;
    buf[padLen - 4] = hi & 0xff; buf[padLen - 3] = (hi >>> 8) & 0xff;
    buf[padLen - 2] = (hi >>> 16) & 0xff; buf[padLen - 1] = (hi >>> 24) & 0xff;
    var a0 = 0x67452301, b0 = 0xefcdab89, c0 = 0x98badcfe, d0 = 0x10325476;
    var M = new Uint32Array(16);
    for (var off = 0; off < padLen; off += 64) {
      for (var t = 0; t < 16; t++) {
        var j = off + t * 4;
        M[t] = (buf[j] | (buf[j + 1] << 8) | (buf[j + 2] << 16) | (buf[j + 3] << 24)) >>> 0;
      }
      var A = a0, B = b0, C = c0, D = d0;
      for (var i = 0; i < 64; i++) {
        var F, g;
        if (i < 16) { F = (B & C) | (~B & D); g = i; }
        else if (i < 32) { F = (D & B) | (~D & C); g = (5 * i + 1) % 16; }
        else if (i < 48) { F = B ^ C ^ D; g = (3 * i + 5) % 16; }
        else { F = C ^ (B | ~D); g = (7 * i) % 16; }
        var sum = (F + A + MD5_K[i] + M[g]) >>> 0;
        var s = MD5_S[i];
        A = D; D = C; C = B;
        B = (B + ((sum << s) | (sum >>> (32 - s)))) >>> 0;
      }
      a0 = (a0 + A) >>> 0; b0 = (b0 + B) >>> 0; c0 = (c0 + C) >>> 0; d0 = (d0 + D) >>> 0;
    }
    var out = new Uint8Array(16);
    var words = [a0, b0, c0, d0];
    for (var z = 0; z < 4; z++) {
      out[z * 4] = words[z] & 0xff;
      out[z * 4 + 1] = (words[z] >>> 8) & 0xff;
      out[z * 4 + 2] = (words[z] >>> 16) & 0xff;
      out[z * 4 + 3] = (words[z] >>> 24) & 0xff;
    }
    return out;
  }

  // AES-128/192/256 block cipher
  var SBOX = new Uint8Array([
    0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
    0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
    0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
    0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
    0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
    0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
    0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
    0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
    0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
    0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
    0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
    0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
    0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
    0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
    0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
    0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16,
  ]);
  var INV_SBOX = (function () {
    var inv = new Uint8Array(256);
    for (var i = 0; i < 256; i++) inv[SBOX[i]] = i;
    return inv;
  })();
  var RCON = new Uint8Array([0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1b,0x36]);

  function xtime(x) { return ((x << 1) ^ ((x & 0x80) ? 0x1b : 0)) & 0xff; }
  function gmul(a, b) {
    var p = 0;
    for (var i = 0; i < 8; i++) {
      if (b & 1) p ^= a;
      a = xtime(a);
      b >>= 1;
    }
    return p;
  }

  function aesExpandKey(key) {
    var nk = key.length >> 2;
    var nr = nk + 6;
    var rk = new Uint8Array((nr + 1) * 16);
    rk.set(key);
    for (var i = nk; i < (nr + 1) * 4; i++) {
      var prev = (i - 1) * 4;
      var t0 = rk[prev], t1 = rk[prev + 1], t2 = rk[prev + 2], t3 = rk[prev + 3];
      if (i % nk === 0) {
        var tmp = t0;
        t0 = SBOX[t1] ^ RCON[(i / nk) - 1];
        t1 = SBOX[t2];
        t2 = SBOX[t3];
        t3 = SBOX[tmp];
      } else if (nk > 6 && (i % nk) === 4) {
        t0 = SBOX[t0]; t1 = SBOX[t1]; t2 = SBOX[t2]; t3 = SBOX[t3];
      }
      var back = (i - nk) * 4;
      var cur = i * 4;
      rk[cur] = rk[back] ^ t0;
      rk[cur + 1] = rk[back + 1] ^ t1;
      rk[cur + 2] = rk[back + 2] ^ t2;
      rk[cur + 3] = rk[back + 3] ^ t3;
    }
    return { rk: rk, nr: nr };
  }

  function aesEncryptBlock(block, exp) {
    var rk = exp.rk, nr = exp.nr;
    var s = new Uint8Array(block);
    var i;
    for (i = 0; i < 16; i++) s[i] ^= rk[i];
    for (var r = 1; r <= nr; r++) {
      for (i = 0; i < 16; i++) s[i] = SBOX[s[i]];
      var t1 = s[1]; s[1] = s[5]; s[5] = s[9]; s[9] = s[13]; s[13] = t1;
      var t2 = s[2]; s[2] = s[10]; s[10] = t2;
      var t6 = s[6]; s[6] = s[14]; s[14] = t6;
      var t3 = s[15]; s[15] = s[11]; s[11] = s[7]; s[7] = s[3]; s[3] = t3;
      if (r < nr) {
        for (var c = 0; c < 16; c += 4) {
          var a0 = s[c], a1 = s[c + 1], a2 = s[c + 2], a3 = s[c + 3];
          s[c] = gmul(a0, 2) ^ gmul(a1, 3) ^ a2 ^ a3;
          s[c + 1] = a0 ^ gmul(a1, 2) ^ gmul(a2, 3) ^ a3;
          s[c + 2] = a0 ^ a1 ^ gmul(a2, 2) ^ gmul(a3, 3);
          s[c + 3] = gmul(a0, 3) ^ a1 ^ a2 ^ gmul(a3, 2);
        }
      }
      var off = r * 16;
      for (i = 0; i < 16; i++) s[i] ^= rk[off + i];
    }
    return s;
  }

  function aesDecryptBlock(block, exp) {
    var rk = exp.rk, nr = exp.nr;
    var s = new Uint8Array(block);
    var i;
    var off = nr * 16;
    for (i = 0; i < 16; i++) s[i] ^= rk[off + i];
    for (var r = nr - 1; r >= 0; r--) {
      var t3 = s[13]; s[13] = s[9]; s[9] = s[5]; s[5] = s[1]; s[1] = t3;
      var t2 = s[2]; s[2] = s[10]; s[10] = t2;
      var t6 = s[6]; s[6] = s[14]; s[14] = t6;
      var t15 = s[3]; s[3] = s[7]; s[7] = s[11]; s[11] = s[15]; s[15] = t15;
      for (i = 0; i < 16; i++) s[i] = INV_SBOX[s[i]];
      var roff = r * 16;
      for (i = 0; i < 16; i++) s[i] ^= rk[roff + i];
      if (r > 0) {
        for (var c = 0; c < 16; c += 4) {
          var a0 = s[c], a1 = s[c + 1], a2 = s[c + 2], a3 = s[c + 3];
          s[c] = gmul(a0, 14) ^ gmul(a1, 11) ^ gmul(a2, 13) ^ gmul(a3, 9);
          s[c + 1] = gmul(a0, 9) ^ gmul(a1, 14) ^ gmul(a2, 11) ^ gmul(a3, 13);
          s[c + 2] = gmul(a0, 13) ^ gmul(a1, 9) ^ gmul(a2, 14) ^ gmul(a3, 11);
          s[c + 3] = gmul(a0, 11) ^ gmul(a1, 13) ^ gmul(a2, 9) ^ gmul(a3, 14);
        }
      }
    }
    return s;
  }

  function adjustAesKey(rawKey) {
    var kb = asBytes(rawKey);
    if (kb.length === 16 || kb.length === 24 || kb.length === 32) return kb;
    return sha256Bytes(kb);
  }

  function evpBytesToKey(passwordBytes, saltBytes, keyLen, ivLen) {
    var d = new Uint8Array(keyLen + ivLen);
    var filled = 0;
    var prev = new Uint8Array(0);
    while (filled < d.length) {
      var chunk = new Uint8Array(prev.length + passwordBytes.length + saltBytes.length);
      chunk.set(prev, 0);
      chunk.set(passwordBytes, prev.length);
      chunk.set(saltBytes, prev.length + passwordBytes.length);
      prev = md5Bytes(chunk);
      var take = Math.min(prev.length, d.length - filled);
      d.set(prev.subarray(0, take), filled);
      filled += take;
    }
    return { key: d.subarray(0, keyLen), iv: d.subarray(keyLen, keyLen + ivLen) };
  }

  function pkcs7Pad(data) {
    var pad = 16 - (data.length % 16);
    var out = new Uint8Array(data.length + pad);
    out.set(data);
    for (var i = data.length; i < out.length; i++) out[i] = pad;
    return out;
  }

  function pkcs7Unpad(data) {
    if (!data.length || data.length % 16 !== 0) {
      throw new Error('Invalid AES block size');
    }
    var pad = data[data.length - 1];
    if (pad < 1 || pad > 16) throw new Error('Invalid PKCS7 padding');
    for (var i = data.length - pad; i < data.length; i++) {
      if (data[i] !== pad) throw new Error('Invalid PKCS7 padding bytes');
    }
    return data.subarray(0, data.length - pad);
  }

  function randomIv16() {
    var iv = new Uint8Array(16);
    for (var i = 0; i < 16; i++) iv[i] = (Math.random() * 256) | 0;
    return iv;
  }

  function aesCbcEncrypt(plainBytes, keyBytes, ivBytes) {
    var exp = aesExpandKey(keyBytes);
    var padded = pkcs7Pad(plainBytes);
    var out = new Uint8Array(padded.length);
    var prev = new Uint8Array(ivBytes);
    for (var off = 0; off < padded.length; off += 16) {
      var blk = new Uint8Array(16);
      for (var i = 0; i < 16; i++) blk[i] = padded[off + i] ^ prev[i];
      var enc = aesEncryptBlock(blk, exp);
      out.set(enc, off);
      prev = enc;
    }
    return out;
  }

  function aesCbcDecrypt(cipherBytes, keyBytes, ivBytes) {
    if (!cipherBytes.length || cipherBytes.length % 16 !== 0) {
      throw new Error('Invalid ciphertext length');
    }
    var exp = aesExpandKey(keyBytes);
    var out = new Uint8Array(cipherBytes.length);
    var prev = new Uint8Array(ivBytes);
    for (var off = 0; off < cipherBytes.length; off += 16) {
      var blk = cipherBytes.subarray(off, off + 16);
      var dec = aesDecryptBlock(blk, exp);
      for (var i = 0; i < 16; i++) out[off + i] = dec[i] ^ prev[i];
      prev = blk;
    }
    return pkcs7Unpad(out);
  }

  global.CryptoJS = {
    enc: _Enc,
    SHA256: function (msg) { return new WordArray(sha256Bytes(msg)); },
    MD5: function (msg) { return new WordArray(md5Bytes(msg)); },
    AES: {
      encrypt: function (message, key, cfg) {
        var plainBytes = asBytes(message);
        var keyBytes = adjustAesKey(key);
        var ivBytes;
        var prependIv = false;
        if (cfg && cfg.iv != null) {
          ivBytes = asBytes(cfg.iv);
          if (ivBytes.length !== 16) throw new Error('IV length must be 16 bytes');
        } else {
          ivBytes = randomIv16();
          prependIv = true;
        }
        var cipher = aesCbcEncrypt(plainBytes, keyBytes, ivBytes);
        if (prependIv) {
          var combined = new Uint8Array(16 + cipher.length);
          combined.set(ivBytes, 0);
          combined.set(cipher, 16);
          return new WordArray(combined, ivBytes);
        }
        return new WordArray(cipher, ivBytes);
      },
      decrypt: function (ciphertext, key, cfg) {
        var decoded = typeof ciphertext === 'string'
          ? base64ToBytes(ciphertext)
          : asBytes(ciphertext);
        var rawPassword = asBytes(key);
        var keyBytes;
        var ivBytes;
        var cipherBytes;
        if (cfg && cfg.iv != null) {
          ivBytes = asBytes(cfg.iv);
          if (ivBytes.length !== 16) throw new Error('IV length must be 16 bytes');
          keyBytes = adjustAesKey(rawPassword);
          cipherBytes = decoded;
        } else if (
          decoded.length >= 16 &&
          decoded[0] === 0x53 && decoded[1] === 0x61 && decoded[2] === 0x6c && decoded[3] === 0x74 &&
          decoded[4] === 0x65 && decoded[5] === 0x64 && decoded[6] === 0x5f && decoded[7] === 0x5f
        ) {
          var salt = decoded.subarray(8, 16);
          var derived = evpBytesToKey(rawPassword, salt, 32, 16);
          keyBytes = derived.key;
          ivBytes = derived.iv;
          cipherBytes = decoded.subarray(16);
        } else if (decoded.length >= 32) {
          ivBytes = decoded.subarray(0, 16);
          cipherBytes = decoded.subarray(16);
          keyBytes = adjustAesKey(rawPassword);
        } else {
          throw new Error('Ciphertext too short to extract IV');
        }
        var plain = aesCbcDecrypt(cipherBytes, keyBytes, ivBytes);
        return new WordArray(plain, ivBytes);
      },
    },
  };

  // --- HTML Parser & CSS Selector Engine (LoadDoc / new Doc) ---
  var VOID_TAGS = {
    area:1, base:1, br:1, col:1, embed:1, hr:1, img:1, input:1,
    link:1, meta:1, param:1, source:1, track:1, wbr:1,
  };
  var NAMED_ENTITIES = {
    amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", '#39': "'",
    nbsp: '\u00a0', ndash: '\u2013', mdash: '\u2014', lsquo: '\u2018',
    rsquo: '\u2019', ldquo: '\u201c', rdquo: '\u201d', hellip: '\u2026',
    copy: '\u00a9', reg: '\u00ae', trade: '\u2122', times: '\u00d7',
    agrave: '\u00e0', acirc: '\u00e2', auml: '\u00e4', ccedil: '\u00e7',
    egrave: '\u00e8', eacute: '\u00e9', ecirc: '\u00ea', euml: '\u00eb',
    icirc: '\u00ee', iuml: '\u00ef', ocirc: '\u00f4', ouml: '\u00f6',
    ugrave: '\u00f9', ucirc: '\u00fb', uuml: '\u00fc', oelig: '\u0153',
    Egrave: '\u00c8', Eacute: '\u00c9', Ecirc: '\u00ca', Agrave: '\u00c0',
  };

  function decodeHtmlEntities(str) {
    if (!str || str.indexOf('&') === -1) return str || '';
    return str.replace(/&(#x[0-9a-fA-F]+|#[0-9]+|[A-Za-z0-9]+);/g, function (m, entity) {
      if (entity[0] === '#') {
        var cp = (entity[1] === 'x' || entity[1] === 'X')
          ? parseInt(entity.slice(2), 16)
          : parseInt(entity.slice(1), 10);
        if (!isNaN(cp) && cp > 0 && cp <= 0x10ffff) {
          try { return String.fromCodePoint(cp); } catch (_e) {}
        }
        return m;
      }
      return Object.prototype.hasOwnProperty.call(NAMED_ENTITIES, entity) ? NAMED_ENTITIES[entity] : m;
    });
  }

  function escapeHtmlText(str) {
    return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function escapeHtmlAttr(str) {
    return escapeHtmlText(str).replace(/"/g, '&quot;');
  }

  function parseHtml(html) {
    html = String(html || '');
    var root = { type: 'root', tag: '#document', attrs: {}, children: [], parent: null };
    var stack = [root];
    var i = 0, n = html.length;

    function pushChild(node) {
      var parent = stack[stack.length - 1];
      node.parent = parent;
      parent.children.push(node);
    }

    while (i < n) {
      var lt = html.indexOf('<', i);
      if (lt === -1) {
        if (i < n) pushChild({ type: 'text', data: decodeHtmlEntities(html.slice(i)), parent: null });
        break;
      }
      if (lt > i) {
        pushChild({ type: 'text', data: decodeHtmlEntities(html.slice(i, lt)), parent: null });
      }
      if (html.startsWith('<!--', lt)) {
        var cEnd = html.indexOf('-->', lt + 4);
        var commentText = cEnd === -1 ? html.slice(lt + 4) : html.slice(lt + 4, cEnd);
        pushChild({ type: 'comment', data: commentText, parent: null });
        i = cEnd === -1 ? n : cEnd + 3;
        continue;
      }
      if (html[lt + 1] === '!' || html[lt + 1] === '?') {
        var gtD = html.indexOf('>', lt + 2);
        i = gtD === -1 ? n : gtD + 1;
        continue;
      }
      if (html[lt + 1] === '/') {
        var gtC = html.indexOf('>', lt + 2);
        var closeTag = (gtC === -1 ? html.slice(lt + 2) : html.slice(lt + 2, gtC)).trim().toLowerCase();
        for (var sp = stack.length - 1; sp > 0; sp--) {
          if (stack[sp].tag === closeTag) {
            stack.length = sp;
            break;
          }
        }
        i = gtC === -1 ? n : gtC + 1;
        continue;
      }

      // Opening tag <tagName ...attrs...>
      var p = lt + 1;
      while (p < n && !/[\s\/>]/.test(html[p])) p++;
      var tag = html.slice(lt + 1, p).toLowerCase();
      if (!tag) {
        pushChild({ type: 'text', data: '<', parent: null });
        i = lt + 1;
        continue;
      }
      var attrs = {};
      var selfClosing = false;
      while (p < n) {
        while (p < n && /\s/.test(html[p])) p++;
        if (p >= n) break;
        if (html[p] === '>') { p++; break; }
        if (html[p] === '/' && html[p + 1] === '>') { selfClosing = true; p += 2; break; }
        var aStart = p;
        while (p < n && !/[\s=/>]/.test(html[p])) p++;
        var aName = html.slice(aStart, p).toLowerCase();
        while (p < n && /\s/.test(html[p])) p++;
        var aVal = '';
        if (p < n && html[p] === '=') {
          p++;
          while (p < n && /\s/.test(html[p])) p++;
          if (p < n && (html[p] === '"' || html[p] === "'")) {
            var q = html[p++];
            var vStart = p;
            var qEnd = html.indexOf(q, p);
            if (qEnd === -1) { aVal = html.slice(vStart); p = n; }
            else { aVal = html.slice(vStart, qEnd); p = qEnd + 1; }
          } else {
            var uStart = p;
            while (p < n && !/[\s>]/.test(html[p])) p++;
            aVal = html.slice(uStart, p);
          }
        }
        if (aName && !Object.prototype.hasOwnProperty.call(attrs, aName)) {
          attrs[aName] = decodeHtmlEntities(aVal);
        }
      }
      var elem = { type: 'tag', tag: tag, attrs: attrs, children: [], parent: null };
      pushChild(elem);
      i = p;

      if (tag === 'script' || tag === 'style') {
        if (!selfClosing) {
          var closeRe = new RegExp('<\\/' + tag + '\\s*>', 'i');
          var rest = html.slice(i);
          var m = closeRe.exec(rest);
          var rawText = m ? rest.slice(0, m.index) : rest;
          if (rawText) pushChild({ type: 'text', data: rawText, parent: elem });
          elem.children.forEach(function (ch) { ch.parent = elem; });
          i = m ? i + m.index + m[0].length : n;
        }
      } else if (!selfClosing && !VOID_TAGS[tag]) {
        stack.push(elem);
      }
    }
    return root;
  }

  function nodeText(node) {
    if (!node) return '';
    if (node.type === 'text') return node.data || '';
    if (node.type === 'comment') return '';
    var out = '';
    var ch = node.children || [];
    for (var i = 0; i < ch.length; i++) out += nodeText(ch[i]);
    return out;
  }

  function serializeNode(node) {
    if (!node) return '';
    if (node.type === 'text') return escapeHtmlText(node.data);
    if (node.type === 'comment') return '<!--' + node.data + '-->';
    if (node.type !== 'tag') return serializeInner(node);
    var attrsStr = '';
    var keys = Object.keys(node.attrs || {});
    for (var i = 0; i < keys.length; i++) {
      attrsStr += ' ' + keys[i] + '="' + escapeHtmlAttr(node.attrs[keys[i]]) + '"';
    }
    if (VOID_TAGS[node.tag]) return '<' + node.tag + attrsStr + '>';
    return '<' + node.tag + attrsStr + '>' + serializeInner(node) + '</' + node.tag + '>';
  }

  function serializeInner(node) {
    if (!node || !node.children) return '';
    var out = '';
    for (var i = 0; i < node.children.length; i++) out += serializeNode(node.children[i]);
    return out;
  }

  // Selector parser & matcher
  function splitSelectorList(sel) {
    var parts = [];
    var cur = '';
    var p = 0, b = 0, q = '';
    for (var i = 0; i < sel.length; i++) {
      var ch = sel[i];
      if (q) {
        cur += ch;
        if (ch === '\\' && i + 1 < sel.length) { cur += sel[++i]; continue; }
        if (ch === q) q = '';
        continue;
      }
      if (ch === '"' || ch === "'") { q = ch; cur += ch; continue; }
      if (ch === '(') p++;
      else if (ch === ')' && p > 0) p--;
      else if (ch === '[') b++;
      else if (ch === ']' && b > 0) b--;
      if (ch === ',' && p === 0 && b === 0) {
        if (cur.trim()) parts.push(cur.trim());
        cur = '';
        continue;
      }
      cur += ch;
    }
    if (cur.trim()) parts.push(cur.trim());
    return parts;
  }

  function parseComplexSelector(sel) {
    var tokens = []; // sequence of { compound, comb } where comb applies BEFORE next compound
    var i = 0, n = sel.length;
    function readBalanced(openCh, closeCh) {
      var start = i;
      var depth = 0, quote = '';
      while (i < n) {
        var c = sel[i];
        if (quote) {
          if (c === '\\') i += 2;
          else if (c === quote) { quote = ''; i++; }
          else i++;
          continue;
        }
        if (c === '"' || c === "'") { quote = c; i++; continue; }
        if (c === openCh) depth++;
        else if (c === closeCh) { depth--; i++; if (depth === 0) break; continue; }
        i++;
      }
      return sel.slice(start, i);
    }
    while (i < n) {
      while (i < n && /\s/.test(sel[i])) i++;
      if (i >= n) break;
      var compStart = i;
      while (i < n) {
        var c = sel[i];
        if (c === '[') readBalanced('[', ']');
        else if (c === '(') readBalanced('(', ')');
        else if (/[\s>+~]/.test(c)) break;
        else i++;
      }
      var compound = sel.slice(compStart, i);
      while (i < n && /\s/.test(sel[i])) i++;
      var comb = null;
      if (i < n && (sel[i] === '>' || sel[i] === '+' || sel[i] === '~')) {
        comb = sel[i++];
        while (i < n && /\s/.test(sel[i])) i++;
      } else if (i < n) {
        comb = ' ';
      }
      tokens.push({ compound: parseCompound(compound), comb: comb });
    }
    return tokens;
  }

  function parseCompound(str) {
    var conds = { tag: null, id: [], classes: [], attrs: [], pseudos: [] };
    var i = 0, n = str.length;
    if (i < n && str[i] === '*') { conds.tag = '*'; i++; }
    else if (i < n && /[A-Za-z_-]/.test(str[i])) {
      var s = i;
      while (i < n && /[A-Za-z0-9_-]/.test(str[i])) i++;
      conds.tag = str.slice(s, i).toLowerCase();
    }
    while (i < n) {
      var ch = str[i];
      if (ch === '#' || ch === '.') {
        i++;
        var ns = i, buf = '';
        while (i < n && !/[#.:\[\s>+~]/.test(str[i])) {
          if (str[i] === '\\' && i + 1 < n) { buf += str[i + 1]; i += 2; }
          else buf += str[i++];
        }
        if (ch === '#') conds.id.push(buf);
        else conds.classes.push(buf);
      } else if (ch === '[') {
        var end = str.indexOf(']', i);
        if (end === -1) break;
        var inner = str.slice(i + 1, end).trim();
        i = end + 1;
        var am = inner.match(/^([^\s=~|^$*\]]+)\s*(?:([~|^$*]?=)\s*([\s\S]*?))?(?:\s+([iIsS]))?$/);
        if (am) {
          var val = am[3] || '';
          var ci = am[4] && am[4].toLowerCase() === 'i';
          if (val.length >= 2 && ((val[0] === '"' && val[val.length - 1] === '"') || (val[0] === "'" && val[val.length - 1] === "'"))) {
            val = val.slice(1, -1);
          } else if (val && /\s+[iIsS]$/.test(val)) {
            ci = val.slice(-1).toLowerCase() === 'i';
            val = val.slice(0, -1).trim();
          }
          conds.attrs.push({ name: am[1].toLowerCase(), op: am[2] || '', val: val, ci: ci });
        }
      } else if (ch === ':') {
        i++;
        if (str[i] === ':') i++;
        var ps = i;
        while (i < n && /[A-Za-z0-9_-]/.test(str[i])) i++;
        var pname = str.slice(ps, i).toLowerCase();
        var parg = '';
        if (i < n && str[i] === '(') {
          var depth = 0, aStart = i + 1, q = '';
          while (i < n) {
            var c2 = str[i];
            if (q) { if (c2 === '\\') i += 2; else if (c2 === q) { q = ''; i++; } else i++; continue; }
            if (c2 === '"' || c2 === "'") { q = c2; i++; continue; }
            if (c2 === '(') depth++;
            else if (c2 === ')') { depth--; if (depth === 0) { parg = str.slice(aStart, i); i++; break; } }
            i++;
          }
        }
        conds.pseudos.push({ name: pname, arg: parg });
      } else {
        i++;
      }
    }
    return conds;
  }

  function nthMatches(index1, expr) {
    expr = String(expr || '').trim().toLowerCase();
    if (expr === 'odd') expr = '2n+1';
    else if (expr === 'even') expr = '2n';
    var m = expr.match(/^([+-]?\d*)?n\s*([+-]\s*\d+)?$/);
    if (!m) {
      var fixed = parseInt(expr, 10);
      return !isNaN(fixed) && index1 === fixed;
    }
    var aStr = m[1];
    var a = (aStr === '' || aStr === '+' || aStr == null) ? 1 : (aStr === '-' ? -1 : parseInt(aStr, 10));
    var b = m[2] ? parseInt(m[2].replace(/\s+/g, ''), 10) : 0;
    if (a === 0) return index1 === b;
    var diff = index1 - b;
    return diff % a === 0 && diff / a >= 0;
  }

  function elemSiblings(node) {
    if (!node.parent || !node.parent.children) return [];
    return node.parent.children.filter(function (c) { return c.type === 'tag'; });
  }

  function matchesCompound(node, conds) {
    if (!node || node.type !== 'tag') return false;
    if (conds.tag && conds.tag !== '*' && node.tag !== conds.tag) return false;
    for (var i = 0; i < conds.id.length; i++) {
      if (node.attrs.id !== conds.id[i]) return false;
    }
    if (conds.classes.length) {
      var clsList = (node.attrs['class'] || '').trim().split(/\s+/);
      for (var j = 0; j < conds.classes.length; j++) {
        if (clsList.indexOf(conds.classes[j]) === -1) return false;
      }
    }
    for (var k = 0; k < conds.attrs.length; k++) {
      var a = conds.attrs[k];
      if (!Object.prototype.hasOwnProperty.call(node.attrs, a.name)) return false;
      if (a.op) {
        var actual = String(node.attrs[a.name] || '');
        var target = a.val;
        if (a.ci) { actual = actual.toLowerCase(); target = target.toLowerCase(); }
        if (a.op === '=' && actual !== target) return false;
        if (a.op === '~=' && (!target || actual.trim().split(/\s+/).indexOf(target) === -1)) return false;
        if (a.op === '|=' && actual !== target && !actual.startsWith(target + '-')) return false;
        if (a.op === '^=' && (!target || !actual.startsWith(target))) return false;
        if (a.op === '$=' && (!target || !actual.endsWith(target))) return false;
        if (a.op === '*=' && (!target || actual.indexOf(target) === -1)) return false;
      }
    }
    for (var p = 0; p < conds.pseudos.length; p++) {
      var ps = conds.pseudos[p];
      var sibs;
      if (ps.name === 'first-child') {
        sibs = elemSiblings(node);
        if (sibs[0] !== node) return false;
      } else if (ps.name === 'last-child') {
        sibs = elemSiblings(node);
        if (sibs[sibs.length - 1] !== node) return false;
      } else if (ps.name === 'only-child') {
        sibs = elemSiblings(node);
        if (sibs.length !== 1 || sibs[0] !== node) return false;
      } else if (ps.name === 'nth-child') {
        sibs = elemSiblings(node);
        var idx1 = sibs.indexOf(node) + 1;
        if (idx1 <= 0 || !nthMatches(idx1, ps.arg)) return false;
      } else if (ps.name === 'nth-last-child') {
        sibs = elemSiblings(node);
        var idxFromEnd = sibs.length - sibs.indexOf(node);
        if (idxFromEnd <= 0 || !nthMatches(idxFromEnd, ps.arg)) return false;
      } else if (ps.name === 'first-of-type') {
        sibs = elemSiblings(node).filter(function (s) { return s.tag === node.tag; });
        if (sibs[0] !== node) return false;
      } else if (ps.name === 'last-of-type') {
        sibs = elemSiblings(node).filter(function (s) { return s.tag === node.tag; });
        if (sibs[sibs.length - 1] !== node) return false;
      } else if (ps.name === 'empty') {
        if (node.children && node.children.some(function (c) {
          return c.type === 'tag' || (c.type === 'text' && c.data.length > 0);
        })) return false;
      } else if (ps.name === 'not') {
        if (matchesAnySelector(node, ps.arg)) return false;
      } else if (ps.name === 'has') {
        if (!queryDescendants([node], ps.arg).length) return false;
      } else if (ps.name === 'contains') {
        var needle = ps.arg.trim().replace(/^["']|["']$/g, '');
        if (nodeText(node).indexOf(needle) === -1) return false;
      }
    }
    return true;
  }

  function matchesComplex(node, parts, partIdx) {
    if (!matchesCompound(node, parts[partIdx].compound)) return false;
    if (partIdx === 0) return true;
    var comb = parts[partIdx - 1].comb;
    if (comb === '>') {
      return node.parent && node.parent.type === 'tag' && matchesComplex(node.parent, parts, partIdx - 1);
    }
    if (comb === ' ') {
      var anc = node.parent;
      while (anc && anc.type === 'tag') {
        if (matchesComplex(anc, parts, partIdx - 1)) return true;
        anc = anc.parent;
      }
      return false;
    }
    if (comb === '+') {
      var sibs = elemSiblings(node);
      var pos = sibs.indexOf(node);
      return pos > 0 && matchesComplex(sibs[pos - 1], parts, partIdx - 1);
    }
    if (comb === '~') {
      var sibs2 = elemSiblings(node);
      var pos2 = sibs2.indexOf(node);
      for (var s = pos2 - 1; s >= 0; s--) {
        if (matchesComplex(sibs2[s], parts, partIdx - 1)) return true;
      }
      return false;
    }
    return false;
  }

  function matchesAnySelector(node, selectorStr) {
    var list = splitSelectorList(String(selectorStr || ''));
    for (var i = 0; i < list.length; i++) {
      var parts = parseComplexSelector(list[i]);
      if (parts.length && matchesComplex(node, parts, parts.length - 1)) return true;
    }
    return false;
  }

  function collectAllDescendants(roots) {
    var out = [];
    function walk(node) {
      var ch = node.children || [];
      for (var i = 0; i < ch.length; i++) {
        if (ch[i].type === 'tag') {
          out.push(ch[i]);
          walk(ch[i]);
        }
      }
    }
    for (var r = 0; r < roots.length; r++) walk(roots[r]);
    return out;
  }

  function uniqueNodes(nodes) {
    var seen = new Set();
    var out = [];
    for (var i = 0; i < nodes.length; i++) {
      if (!seen.has(nodes[i])) {
        seen.add(nodes[i]);
        out.push(nodes[i]);
      }
    }
    return out;
  }

  function queryDescendants(roots, selectorStr) {
    var list = splitSelectorList(String(selectorStr || ''));
    if (!list.length) return [];
    var desc = uniqueNodes(collectAllDescendants(roots));
    var rootSet = new Set(roots);
    var parsed = list.map(parseComplexSelector).filter(function (p) { return p.length > 0; });
    var matched = [];
    for (var i = 0; i < desc.length; i++) {
      var node = desc[i];
      for (var s = 0; s < parsed.length; s++) {
        var parts = parsed[s];
        if (matchesComplexWithin(node, parts, parts.length - 1, rootSet)) {
          matched.push(node);
          break;
        }
      }
    }
    return matched;
  }

  function matchesComplexWithin(node, parts, partIdx, rootSet) {
    if (!matchesCompound(node, parts[partIdx].compound)) return false;
    if (partIdx === 0) return true;
    var comb = parts[partIdx - 1].comb;
    if (comb === '>') {
      return node.parent && node.parent.type === 'tag' && !rootSet.has(node) && matchesComplexWithin(node.parent, parts, partIdx - 1, rootSet);
    }
    if (comb === ' ') {
      var anc = node.parent;
      while (anc && anc.type === 'tag') {
        if (matchesComplexWithin(anc, parts, partIdx - 1, rootSet)) return true;
        if (rootSet.has(anc)) break;
        anc = anc.parent;
      }
      return false;
    }
    if (comb === '+') {
      var sibs = elemSiblings(node);
      var pos = sibs.indexOf(node);
      return pos > 0 && matchesComplexWithin(sibs[pos - 1], parts, partIdx - 1, rootSet);
    }
    if (comb === '~') {
      var sibs2 = elemSiblings(node);
      var pos2 = sibs2.indexOf(node);
      for (var k = pos2 - 1; k >= 0; k--) {
        if (matchesComplexWithin(sibs2[k], parts, partIdx - 1, rootSet)) return true;
      }
      return false;
    }
    return false;
  }

  function wrapSelection(nodes, prevSelection) {
    var list = Array.isArray(nodes) ? nodes : [];
    var sel = {
      _nodes: list,
      length: function () { return list.length; },
      find: function (q) { return wrapSelection(queryDescendants(list, q), sel); },
      children: function (q) {
        var out = [];
        for (var i = 0; i < list.length; i++) {
          var ch = list[i].children || [];
          for (var j = 0; j < ch.length; j++) {
            if (ch[j].type === 'tag' && (!q || matchesAnySelector(ch[j], q))) out.push(ch[j]);
          }
        }
        return wrapSelection(uniqueNodes(out), sel);
      },
      contents: function () {
        var out = [];
        for (var i = 0; i < list.length; i++) {
          var ch = list[i].children || [];
          for (var j = 0; j < ch.length; j++) out.push(ch[j]);
        }
        return wrapSelection(out, sel);
      },
      contentsFiltered: function (q) {
        var out = [];
        for (var i = 0; i < list.length; i++) {
          var ch = list[i].children || [];
          for (var j = 0; j < ch.length; j++) {
            if (ch[j].type === 'tag' && (!q || matchesAnySelector(ch[j], q))) out.push(ch[j]);
          }
        }
        return wrapSelection(out, sel);
      },
      text: function () {
        var out = '';
        for (var i = 0; i < list.length; i++) out += nodeText(list[i]);
        return out;
      },
      html: function () { return list.length ? serializeInner(list[0]) : null; },
      attr: function (name) {
        if (!list.length || list[0].type !== 'tag') return undefined;
        var k = String(name || '').toLowerCase();
        return Object.prototype.hasOwnProperty.call(list[0].attrs, k) ? list[0].attrs[k] : undefined;
      },
      attrs: function () {
        if (!list.length || list[0].type !== 'tag') return {};
        return Object.assign({}, list[0].attrs);
      },
      data: function (name) {
        if (!list.length || list[0].type !== 'tag') return undefined;
        if (name === undefined) {
          var out = null;
          var keys = Object.keys(list[0].attrs);
          for (var i = 0; i < keys.length; i++) {
            if (keys[i].startsWith('data-')) {
              if (!out) out = {};
              out[keys[i]] = list[0].attrs[keys[i]];
            }
          }
          return out || undefined;
        }
        var k = 'data-' + String(name).toLowerCase();
        return Object.prototype.hasOwnProperty.call(list[0].attrs, k) ? list[0].attrs[k] : undefined;
      },
      each: function (fn) {
        if (typeof fn === 'function') {
          for (var i = 0; i < list.length; i++) fn(i, wrapSelection([list[i]], sel));
        }
        return undefined;
      },
      map: function (fn) {
        var out = [];
        if (typeof fn === 'function') {
          for (var i = 0; i < list.length; i++) out.push(fn(i, wrapSelection([list[i]], sel)));
        }
        return out;
      },
      first: function () { return wrapSelection(list.length ? [list[0]] : [], sel); },
      last: function () { return wrapSelection(list.length ? [list[list.length - 1]] : [], sel); },
      eq: function (idx) {
        var n = Number(idx);
        if (n < 0) n = list.length + n;
        return wrapSelection(n >= 0 && n < list.length ? [list[n]] : [], sel);
      },
      parent: function (q) {
        var out = [];
        for (var i = 0; i < list.length; i++) {
          var p = list[i].parent;
          if (p && p.type === 'tag' && (!q || matchesAnySelector(p, q))) out.push(p);
        }
        return wrapSelection(uniqueNodes(out), sel);
      },
      parents: function (q) {
        var out = [];
        for (var i = 0; i < list.length; i++) {
          var p = list[i].parent;
          while (p && p.type === 'tag') {
            if (!q || matchesAnySelector(p, q)) out.push(p);
            p = p.parent;
          }
        }
        return wrapSelection(uniqueNodes(out), sel);
      },
      parentsUntil: function (q, until) {
        var out = [];
        for (var i = 0; i < list.length; i++) {
          var p = list[i].parent;
          while (p && p.type === 'tag') {
            if (q && matchesAnySelector(p, q)) break;
            if (!until || matchesAnySelector(p, until)) out.push(p);
            p = p.parent;
          }
        }
        return wrapSelection(uniqueNodes(out), sel);
      },
      closest: function (q) {
        var out = [];
        for (var i = 0; i < list.length; i++) {
          var p = list[i];
          while (p && p.type === 'tag') {
            if (!q || matchesAnySelector(p, q)) { out.push(p); break; }
            p = p.parent;
          }
        }
        return wrapSelection(uniqueNodes(out), sel);
      },
      next: function (q) {
        var out = [];
        for (var i = 0; i < list.length; i++) {
          var sibs = elemSiblings(list[i]);
          var pos = sibs.indexOf(list[i]);
          if (pos >= 0 && pos + 1 < sibs.length) {
            var nx = sibs[pos + 1];
            if (!q || matchesAnySelector(nx, q)) out.push(nx);
          }
        }
        return wrapSelection(uniqueNodes(out), sel);
      },
      nextAll: function (q) {
        var out = [];
        for (var i = 0; i < list.length; i++) {
          var sibs = elemSiblings(list[i]);
          var pos = sibs.indexOf(list[i]);
          for (var j = pos + 1; pos >= 0 && j < sibs.length; j++) {
            if (!q || matchesAnySelector(sibs[j], q)) out.push(sibs[j]);
          }
        }
        return wrapSelection(uniqueNodes(out), sel);
      },
      nextUntil: function (q, until) {
        var out = [];
        for (var i = 0; i < list.length; i++) {
          var sibs = elemSiblings(list[i]);
          var pos = sibs.indexOf(list[i]);
          for (var j = pos + 1; pos >= 0 && j < sibs.length; j++) {
            if (q && matchesAnySelector(sibs[j], q)) break;
            if (!until || matchesAnySelector(sibs[j], until)) out.push(sibs[j]);
          }
        }
        return wrapSelection(uniqueNodes(out), sel);
      },
      prev: function (q) {
        var out = [];
        for (var i = 0; i < list.length; i++) {
          var sibs = elemSiblings(list[i]);
          var pos = sibs.indexOf(list[i]);
          if (pos > 0 && (!q || matchesAnySelector(sibs[pos - 1], q))) out.push(sibs[pos - 1]);
        }
        return wrapSelection(uniqueNodes(out), sel);
      },
      prevAll: function (q) {
        var out = [];
        for (var i = 0; i < list.length; i++) {
          var sibs = elemSiblings(list[i]);
          var pos = sibs.indexOf(list[i]);
          for (var j = pos - 1; j >= 0; j--) {
            if (!q || matchesAnySelector(sibs[j], q)) out.push(sibs[j]);
          }
        }
        return wrapSelection(uniqueNodes(out), sel);
      },
      prevUntil: function (q, until) {
        var out = [];
        for (var i = 0; i < list.length; i++) {
          var sibs = elemSiblings(list[i]);
          var pos = sibs.indexOf(list[i]);
          for (var j = pos - 1; j >= 0; j--) {
            if (q && matchesAnySelector(sibs[j], q)) break;
            if (!until || matchesAnySelector(sibs[j], until)) out.push(sibs[j]);
          }
        }
        return wrapSelection(uniqueNodes(out), sel);
      },
      siblings: function (q) {
        var out = [];
        for (var i = 0; i < list.length; i++) {
          var sibs = elemSiblings(list[i]);
          for (var j = 0; j < sibs.length; j++) {
            if (sibs[j] !== list[i] && (!q || matchesAnySelector(sibs[j], q))) out.push(sibs[j]);
          }
        }
        return wrapSelection(uniqueNodes(out), sel);
      },
      filter: function (pred) {
        var out = [];
        for (var i = 0; i < list.length; i++) {
          var ok = typeof pred === 'function'
            ? Boolean(pred(i, wrapSelection([list[i]], sel)))
            : matchesAnySelector(list[i], pred);
          if (ok) out.push(list[i]);
        }
        return wrapSelection(out, sel);
      },
      not: function (pred) {
        var out = [];
        for (var i = 0; i < list.length; i++) {
          var hit = typeof pred === 'function'
            ? Boolean(pred(i, wrapSelection([list[i]], sel)))
            : matchesAnySelector(list[i], pred);
          if (!hit) out.push(list[i]);
        }
        return wrapSelection(out, sel);
      },
      is: function (pred) {
        for (var i = 0; i < list.length; i++) {
          var hit = typeof pred === 'function'
            ? Boolean(pred(i, wrapSelection([list[i]], sel)))
            : matchesAnySelector(list[i], pred);
          if (hit) return true;
        }
        return false;
      },
      has: function (q) {
        var out = [];
        for (var i = 0; i < list.length; i++) {
          if (queryDescendants([list[i]], q).length > 0) out.push(list[i]);
        }
        return wrapSelection(out, sel);
      },
      end: function () { return prevSelection || wrapSelection([]); },
    };
    return sel;
  }

  global.LoadDoc = function LoadDoc(html) {
    var root = parseHtml(html);
    var docSel = wrapSelection([root]);
    return function (selector) {
      return docSel.find(selector);
    };
  };

  global.Doc = function Doc(html) {
    var root = parseHtml(html);
    return wrapSelection([root]);
  };

  // --- Network fetch ---
  function normalizeHeadersInput(rawHeaders) {
    var out = {};
    if (!rawHeaders || typeof rawHeaders !== 'object') return out;
    var keys = Object.keys(rawHeaders);
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i];
      if (rawHeaders[k] != null) out[k] = String(rawHeaders[k]);
    }
    return out;
  }

  function makeHeadersProxy(headersObj) {
    var lowerMap = {};
    var keys = Object.keys(headersObj || {});
    for (var i = 0; i < keys.length; i++) {
      lowerMap[keys[i].toLowerCase()] = headersObj[keys[i]];
    }
    var target = Object.assign({}, headersObj || {});
    Object.defineProperty(target, 'get', {
      enumerable: false,
      value: function (name) {
        var lk = String(name || '').toLowerCase();
        return Object.prototype.hasOwnProperty.call(lowerMap, lk) ? lowerMap[lk] : null;
      },
    });
    if (typeof Proxy === 'undefined') return target;
    return new Proxy(target, {
      get: function (t, prop) {
        if (prop === 'get') return t.get;
        if (typeof prop === 'string' && Object.prototype.hasOwnProperty.call(t, prop)) return t[prop];
        if (typeof prop === 'string') {
          var lk = prop.toLowerCase();
          if (Object.prototype.hasOwnProperty.call(lowerMap, lk)) return lowerMap[lk];
        }
        return undefined;
      },
      has: function (t, prop) {
        if (typeof prop !== 'string') return prop in t;
        return Object.prototype.hasOwnProperty.call(lowerMap, prop.toLowerCase());
      },
    });
  }

  global.fetch = async function fetch(url, init) {
    if (typeof url !== 'string' || !url.trim()) {
      throw new TypeError('URL parameter must be a non-empty string');
    }
    if (typeof global.__seanimeHostFetch !== 'function') {
      throw new Error('Seanime network host bridge is not initialized');
    }
    init = init || {};
    var req = {
      url: String(url),
      method: String(init.method || 'GET').toUpperCase(),
      headers: normalizeHeadersInput(init.headers),
      timeout: Number(init.timeout) > 0 ? Number(init.timeout) : 35,
      redirect: String(init.redirect || 'follow'),
      noCloudflareBypass: Boolean(init.noCloudflareBypass),
    };
    if (init.body !== undefined && init.body !== null) {
      if (init.body.__seanimeFormData) {
        req.bodyEncoding = 'formdata';
        req.formFields = init.body.entries();
      } else if (typeof global.URLSearchParams !== 'undefined' && init.body instanceof global.URLSearchParams) {
        req.bodyText = init.body.toString();
        req.contentType = 'application/x-www-form-urlencoded';
      } else if (typeof init.body === 'string') {
        req.bodyText = init.body;
      } else if (init.body instanceof Uint8Array || init.body instanceof ArrayBuffer || ArrayBuffer.isView(init.body)) {
        req.bodyBase64 = bytesToBase64(asBytes(init.body));
      } else if (typeof init.body === 'object') {
        req.bodyText = JSON.stringify(init.body);
        req.contentType = 'application/json';
      } else {
        req.bodyText = String(init.body);
      }
    }

    var rawResp = await global.__seanimeHostFetch(JSON.stringify(req));
    var data = typeof rawResp === 'string' ? JSON.parse(rawResp) : rawResp;
    if (!data || data.error) {
      throw new Error((data && data.error) || 'Network request failed');
    }
    var bodyTextCache = typeof data.bodyText === 'string' ? data.bodyText : null;
    var bodyBytesCache = null;
    function getBytes() {
      if (!bodyBytesCache) {
        bodyBytesCache = data.bodyBase64
          ? base64ToBytes(data.bodyBase64)
          : utf8Encode(bodyTextCache || '');
      }
      return bodyBytesCache;
    }
    function getText() {
      if (bodyTextCache === null) {
        bodyTextCache = utf8Decode(getBytes());
      }
      return bodyTextCache;
    }
    var respObj = {
      status: Number(data.status || 0),
      statusText: String(data.statusText || ''),
      method: String(data.method || req.method),
      ok: Boolean(data.ok),
      url: String(data.url || req.url),
      redirected: Boolean(data.redirected),
      headers: makeHeadersProxy(data.headers || {}),
      rawHeaders: data.rawHeaders || {},
      cookies: data.cookies || {},
      contentType: String(data.contentType || ''),
      contentLength: Number(data.contentLength || 0),
      text: function () { return getText(); },
      json: function () {
        var txt = getText();
        if (!txt) return null;
        try { return JSON.parse(txt); } catch (_e) { return null; }
      },
      bytes: function () { return getBytes(); },
      arrayBuffer: function () {
        var b = getBytes();
        return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
      },
    };
    Object.defineProperty(respObj, 'body', {
      enumerable: true,
      get: function () { return getBytes(); },
    });
    return respObj;
  };

  // --- Execution lifecycle hooks called by Python / Android ---
  global.__seanimeCompile = function (code) {
    var fn = new Function(String(code) + '\n;return typeof Provider !== "undefined" ? Provider : undefined;');
    global.__SeanimeProviderClass = fn.call(global);
    if (typeof global.__SeanimeProviderClass !== 'function') {
      throw new Error('Class Provider introuvable dans cette extension Seanime.');
    }
    return true;
  };

  global.__seanimeInvoke = async function (methodName, argsJson, userConfigJson, defaultsJson, storeJson) {
    _logs = [];
    _userConfig = userConfigJson ? JSON.parse(userConfigJson) : {};
    _configDefaults = defaultsJson ? JSON.parse(defaultsJson) : {};
    if (storeJson) {
      global.$store.reset(JSON.parse(storeJson));
    } else {
      global.$store.removeAll();
    }
    try {
      var ProviderCls = global.__SeanimeProviderClass || global.Provider;
      if (typeof ProviderCls !== 'function') {
        throw new Error('Provider non compilé.');
      }
      var instance = new ProviderCls();
      var fn = instance && instance[methodName];
      if (typeof fn !== 'function') {
        throw new Error('Méthode Seanime introuvable : ' + methodName);
      }
      var args = argsJson ? JSON.parse(argsJson) : [];
      var result = await Promise.resolve(fn.apply(instance, args));
      return JSON.stringify({
        ok: true,
        result: result === undefined ? null : result,
        store: _storeData,
        logs: _logs,
      });
    } catch (err) {
      return JSON.stringify({
        ok: false,
        error: err && err.message ? String(err.message) : String(err),
        stack: err && err.stack ? String(err.stack) : '',
        store: _storeData,
        logs: _logs,
      });
    }
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
