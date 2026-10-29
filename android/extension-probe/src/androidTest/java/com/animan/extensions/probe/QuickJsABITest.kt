package com.animan.extensions.probe

import app.cash.quickjs.QuickJs
import app.cash.quickjs.QuickJsException
import org.junit.Assert.*
import org.junit.Test

class QuickJsABITest {
    interface Counter { fun increment(value: Int): Int }
    interface Doubler { fun twice(value: Int): Int }

    @Test fun rebuilt_original_java_and_jni_abi_executes_bytecode_unicode_and_proxies() {
        QuickJs.create().use { engine ->
            assertEquals(42, engine.evaluate("6 * 7"))
            val text = "Bonjour 日本語 😀"
            assertEquals(text, engine.execute(engine.compile("'$text'", "controlled-fixture.js")))
            engine.set("counter", Counter::class.java, object : Counter {
                override fun increment(value: Int) = value + 1
            })
            assertEquals(42, engine.evaluate("counter.increment(41)"))
            engine.evaluate("var math = { twice: function(value) { return value * 2; } };")
            assertEquals(42, engine.get("math", Doubler::class.java).twice(21))
            try {
                engine.evaluate("throw new Error('controlled-fixture-error')")
                fail("The original exception ABI must be preserved")
            } catch (expected: QuickJsException) {
                assertTrue(expected.message.orEmpty().contains("controlled-fixture-error"))
            }
        }
    }
}
