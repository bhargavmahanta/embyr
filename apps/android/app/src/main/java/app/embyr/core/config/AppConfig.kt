package app.embyr.core.config

import app.embyr.BuildConfig
import java.net.URI

interface AppConfig {
    val embyrApiBaseUrl: String
    val supabaseUrl: String
    val supabasePublishableKey: String
}

class BuildAppConfig : AppConfig {
    override val embyrApiBaseUrl = requireHttpsUrl(BuildConfig.EMBYR_API_BASE_URL, "EMBYR_API_BASE_URL")
    override val supabaseUrl = requireHttpsUrl(BuildConfig.SUPABASE_URL, "SUPABASE_URL")
    override val supabasePublishableKey = BuildConfig.SUPABASE_PUBLISHABLE_KEY.also {
        require(it.startsWith("sb_publishable_") && it.length > "sb_publishable_".length) {
            "SUPABASE_PUBLISHABLE_KEY must be a client-safe publishable key"
        }
    }

    private fun requireHttpsUrl(raw: String, name: String): String {
        val value = raw.trim()
        val uri = runCatching { URI(value) }.getOrNull()
        require(
            uri?.scheme == "https" && !uri.host.isNullOrBlank() &&
                uri.userInfo == null && uri.rawQuery == null && uri.rawFragment == null,
        ) {
            "$name must be an HTTPS base URL without credentials, query, or fragment"
        }
        return value.trimEnd('/') + "/"
    }
}
