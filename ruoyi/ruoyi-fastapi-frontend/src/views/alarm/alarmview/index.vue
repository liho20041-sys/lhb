<template>
  <div class="app-container">
    <el-row :gutter="10" class="mb8">
      <el-col :span="1.5">
        <el-button type="primary" plain icon="Refresh" @click="getList">刷新</el-button>
      </el-col>
      <el-col :span="1.5">
        <el-button icon="Back" @click="goHome">返回首页</el-button>
      </el-col>
      <el-col :span="6">
        <el-tag type="success" effect="plain" style="margin-top: 6px">共 {{ total }} 条告警</el-tag>
      </el-col>
    </el-row>

    <el-table v-loading="loading" :data="alarmList" border stripe height="calc(100vh - 210px)">
      <el-table-column label="时间" prop="time" width="190" />
      <el-table-column label="摄像头" prop="cameraName" width="170" show-overflow-tooltip />
      <el-table-column label="位置" prop="location" width="180" show-overflow-tooltip />
      <el-table-column label="告警内容" prop="details" min-width="360" show-overflow-tooltip />
      <el-table-column label="快照" width="120" align="center">
        <template #default="scope">
          <el-image
            v-if="scope.row.snapshot"
            :src="fixUrl(scope.row.snapshot)"
            fit="cover"
            style="width: 88px; height: 50px; border-radius: 4px; cursor: pointer"
            @click="openPreview(scope.row)"
          />
          <span v-else>-</span>
        </template>
      </el-table-column>
    </el-table>

    <!-- 固定预览：只显示点击的那一张，不随表格刷新切换 -->
    <el-image-viewer
      v-if="previewVisible"
      :url-list="previewList"
      :initial-index="0"
      @close="closePreview"
    />
  </div>
</template>

<script setup name="AlarmView">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElImageViewer } from 'element-plus'
import { listAlarm } from '@/api/alarm'

const router = useRouter()
const alarmList = ref([])
const total = ref(0)
const loading = ref(false)
const previewVisible = ref(false)
const previewList = ref([])
let timer = null

function goHome() {
  router.push('/index')
}

function fixUrl(u) {
  if (!u) return ''
  if (u.startsWith('/')) return `${location.protocol}//${location.hostname}:8080${u}`
  return u.replace('127.0.0.1', location.hostname).replace('localhost', location.hostname)
}

function openPreview(row) {
  const u = fixUrl(row.snapshot)
  if (!u) return
  previewList.value = [u]
  previewVisible.value = true
  // 打开预览时暂停自动刷新，避免表格/预览被刷新打断
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

function closePreview() {
  previewVisible.value = false
  previewList.value = []
  if (!timer) {
    timer = setInterval(getList, 5000)
  }
}

async function getList() {
  if (previewVisible.value) return
  loading.value = true
  try {
    const res = await listAlarm({ pageNum: 1, pageSize: 300 })
    alarmList.value = res.rows || []
    total.value = res.total || alarmList.value.length
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  getList()
  timer = setInterval(getList, 5000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>
