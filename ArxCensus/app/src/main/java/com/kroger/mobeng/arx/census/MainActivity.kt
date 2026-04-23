package com.kroger.mobeng.arx.census

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.DividerItemDecoration
import androidx.recyclerview.widget.LinearLayoutManager
import com.kroger.mobeng.arx.census.databinding.ActivityMainBinding
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var repo: StorageRepository
    private val adapter = StorageAdapter()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        setSupportActionBar(binding.toolbar)

        repo = StorageRepository(applicationContext)

        binding.list.layoutManager = LinearLayoutManager(this)
        binding.list.adapter = adapter
        binding.list.addItemDecoration(
            DividerItemDecoration(this, DividerItemDecoration.VERTICAL)
        )

        binding.refresh.setOnRefreshListener { scan() }
        binding.grantButton.setOnClickListener {
            startActivity(UsageAccess.settingsIntent())
        }
    }

    override fun onResume() {
        super.onResume()
        scan()
    }

    private fun scan() {
        if (!UsageAccess.hasPermission(this)) {
            showPermissionPrompt()
            return
        }
        showLoading()
        lifecycleScope.launch {
            val apps = repo.loadAll()
            val totalBytes = apps.sumOf { it.totalBytes }
            binding.summary.text = getString(
                R.string.summary_format,
                apps.size,
                ByteFormat.human(totalBytes)
            )
            adapter.submitList(apps)
            showContent()
        }
    }

    private fun showPermissionPrompt() {
        binding.refresh.isRefreshing = false
        binding.permissionBanner.visibility = android.view.View.VISIBLE
        binding.summary.visibility = android.view.View.GONE
        binding.list.visibility = android.view.View.GONE
    }

    private fun showLoading() {
        binding.permissionBanner.visibility = android.view.View.GONE
        binding.refresh.isRefreshing = true
    }

    private fun showContent() {
        binding.permissionBanner.visibility = android.view.View.GONE
        binding.summary.visibility = android.view.View.VISIBLE
        binding.list.visibility = android.view.View.VISIBLE
        binding.refresh.isRefreshing = false
    }
}
