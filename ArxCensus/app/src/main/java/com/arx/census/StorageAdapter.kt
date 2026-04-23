package com.arx.census

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.arx.census.databinding.ItemAppStorageBinding

class StorageAdapter : ListAdapter<AppStorageInfo, StorageAdapter.VH>(DIFF) {

    class VH(val binding: ItemAppStorageBinding) : RecyclerView.ViewHolder(binding.root)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val inflater = LayoutInflater.from(parent.context)
        return VH(ItemAppStorageBinding.inflate(inflater, parent, false))
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        val item = getItem(position)
        val b = holder.binding
        b.icon.setImageDrawable(item.icon)
        b.label.text = item.label
        b.packageName.text = item.packageName
        b.total.text = ByteFormat.human(item.totalBytes)
        b.breakdown.text = holder.itemView.context.getString(
            R.string.breakdown_format,
            ByteFormat.human(item.appBytes),
            ByteFormat.human(item.dataBytes),
            ByteFormat.human(item.cacheBytes)
        )
        b.systemTag.visibility =
            if (item.isSystem) android.view.View.VISIBLE else android.view.View.GONE
    }

    companion object {
        private val DIFF = object : DiffUtil.ItemCallback<AppStorageInfo>() {
            override fun areItemsTheSame(a: AppStorageInfo, b: AppStorageInfo) =
                a.packageName == b.packageName

            override fun areContentsTheSame(a: AppStorageInfo, b: AppStorageInfo) = a == b
        }
    }
}
