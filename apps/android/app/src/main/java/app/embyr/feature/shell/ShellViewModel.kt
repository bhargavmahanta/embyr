package app.embyr.feature.shell

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import app.embyr.auth.AuthGateway
import kotlinx.coroutines.launch

class ShellViewModel(private val auth: AuthGateway) : ViewModel() {
    val authState = auth.state

    init {
        viewModelScope.launch { auth.restoreSession() }
    }

    class Factory(private val auth: AuthGateway) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            require(modelClass == ShellViewModel::class.java)
            return ShellViewModel(auth) as T
        }
    }
}
