<template>
  <div class="dash">
    <!-- 顶部 -->
    <div class="hero">
      <div class="hero-left">
        <div class="hero-title">时空记忆 · 监控中心</div>
        <div class="hero-sub">实时画面 · 行为告警 · 统一管理</div>
      </div>
      <div class="hero-right">
        <span class="clock">{{ clock }}</span>
        <el-button type="primary" plain icon="Refresh" @click="refreshAll">刷新</el-button>
      </div>
    </div>

    <!-- 统计卡 -->
    <div class="stats">
      <div class="stat" v-for="s in statCards" :key="s.key">
        <div class="stat-k">{{ s.label }}</div>
        <div class="stat-v" :style="{ color: s.color }">{{ s.value }}</div>
      </div>
    </div>

    <!-- Tab -->
    <div class="tabs">
      <button :class="{ active: tab === 'overview' }" @click="onTab('overview')">总览</button>
      <button :class="{ active: tab === 'live' }" @click="onTab('live')">实时监控</button>
      <button :class="{ active: tab === 'alarms' }" @click="onTab('alarms')">告警看板</button>
      <button :class="{ active: tab === 'deviation' }" @click="onTab('deviation')">偏离候选</button>
      <button :class="{ active: tab === 'clues' }" @click="onTab('clues')">线索池</button>
    </div>

    <!-- 总览 -->
    <div v-show="tab === 'overview'" class="grid2">
      <div class="panel">
        <div class="panel-head">
          <span>实时画面（带检测框）</span>
          <el-button link type="primary" @click="onTab('live')">放大 →</el-button>
        </div>
        <img :src="liveUrl" class="live-img" alt="live" />
      </div>
      <div class="panel">
        <div class="panel-head">
          <span>最新告警</span>
          <el-button link type="primary" @click="onTab('alarms')">全部 →</el-button>
        </div>
        <div class="feed">
          <div v-for="a in recentAlarms" :key="a.id" class="feed-item" :class="a.alert_level">
            <div class="feed-top">
              <b>{{ a.event_name || a.event_type || '告警' }}</b>
              <span class="muted">{{ fmtTime(a.time) }}</span>
            </div>
            <div class="feed-desc">{{ a.details }}</div>
            <div class="feed-meta">{{ a.camera_name || a.camera_id }} · {{ a.alert_level }}</div>
          </div>
          <div v-if="!recentAlarms.length" class="empty">暂无告警</div>
        </div>
      </div>
    </div>

    <!-- 实时监控 -->
    <div v-show="tab === 'live'" class="panel">
      <div class="panel-head">
        <el-button icon="Back" @click="onTab('overview')">返回总览</el-button>
        <span>实时画面（带检测框）· YOLO11n</span>
        <a :href="frigateUrl" target="_blank" class="link">打开 Frigate ↗</a>
      </div>
      <img :src="liveUrl" class="live-big" alt="live" />
    </div>

    <!-- 告警看板 -->
    <div v-show="tab === 'alarms'" class="panel">
      <div class="panel-head">
        <el-button icon="Back" @click="onTab('overview')">返回总览</el-button>
        <span>告警看板</span>
        <el-button link type="primary" icon="Refresh" @click="loadAlarms">刷新</el-button>
      </div>

      <!-- 可视化 -->
      <div class="charts">
        <div class="chart-card"><div class="chart-title">按类型分布</div><div ref="typeChartEl" class="chart"></div></div>
        <div class="chart-card"><div class="chart-title">按等级分布</div><div ref="levelChartEl" class="chart"></div></div>
        <div class="chart-card wide"><div class="chart-title">近 24 小时</div><div ref="timeChartEl" class="chart"></div></div>
      </div>

      <!-- 过滤 -->
      <div class="toolbar">
        <el-select v-model="filterType" placeholder="全部类型" clearable style="width: 180px" @change="onFilter">
          <el-option
            v-for="t in stats.by_type || []"
            :key="t.event_type"
            :label="`${t.event_name || t.event_type} (${t.count})`"
            :value="t.event_type"
          />
        </el-select>
        <el-select v-model="filterStatus" placeholder="全部状态" clearable style="width: 150px" @change="onFilter">
          <el-option label="待处理" value="active" />
          <el-option label="已处理" value="handled" />
          <el-option label="已忽略" value="ignored" />
        </el-select>
        <span class="muted">共 {{ alarmTotal }} 条</span>
      </div>

      <el-table :data="alarmItems" size="small" height="340" stripe>
        <el-table-column label="时间" width="180">
          <template #default="{ row }">{{ fmtTime(row.time) }}</template>
        </el-table-column>
        <el-table-column prop="camera_name" label="摄像头" width="150" show-overflow-tooltip />
        <el-table-column label="类型" width="120">
          <template #default="{ row }">{{ row.event_name || row.event_type || '告警' }}</template>
        </el-table-column>
        <el-table-column prop="details" label="详情" min-width="320" show-overflow-tooltip />
        <el-table-column label="等级" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="levelType(row.alert_level)" size="small">{{ row.alert_level }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="轨迹" width="70" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="selectDeviation(row)">查看</el-button>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status === 'handled' ? 'success' : 'info'" size="small">
              {{ row.status === 'handled' ? '已处理' : '待处理' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="快照" width="80" align="center">
          <template #default="{ row }">
            <a v-if="row.snapshot" :href="fixUrl(row.snapshot)" target="_blank" class="link">查看</a>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :page-sizes="[20, 50, 100, 200]"
          :total="alarmTotal"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="onSizeChange"
          @current-change="loadAlarms"
        />
      </div>
    </div>

    <!-- 偏离候选（时空记忆） -->
    <div v-show="tab === 'deviation'" class="panel">
      <div class="panel-head">
        <el-button icon="Back" @click="onTab('overview')">返回总览</el-button>
        <span>偏离候选 · 时空记忆</span>
        <el-button link type="primary" icon="Refresh" @click="loadDeviations">刷新</el-button>
      </div>

      <div class="dev-stats">
        <span>轨迹总数 <b>{{ devStats.tracks || 0 }}</b></span>
        <span>基线组 <b>{{ devStats.baselines || 0 }}</b></span>
        <span>偏离候选 <b>{{ devStats.total || 0 }}</b></span>
        <span>待核查 <b class="dev-hot">{{ devStats.pending || 0 }}</b></span>
        <span>最高分 <b>{{ Number(devStats.max_score || 0).toFixed(2) }}</b></span>
      </div>

      <div class="dev-charts">
        <div class="chart-card">
          <div class="chart-title">偏离分趋势</div>
          <div ref="devScoreChartEl" class="chart"></div>
        </div>
        <div class="chart-card wide">
          <div class="chart-title">
            轨迹曲线
            <span v-if="selectedDeviation" class="muted">· {{ selectedDeviation.trace_id }} · 偏离 {{ Number(selectedDeviation.score).toFixed(2) }}</span>
          </div>
          <div ref="devPathChartEl" class="chart"></div>
        </div>
      </div>

      <el-table :data="deviations" size="small" height="480" stripe>
        <el-table-column label="时间" width="180">
          <template #default="{ row }">{{ fmtTime(row.start_time) }}</template>
        </el-table-column>
        <el-table-column prop="camera_id" label="摄像头" width="110" />
        <el-table-column prop="region_id" label="区域" width="100" />
        <el-table-column label="偏离分" width="90" align="center">
          <template #default="{ row }">
            <span :style="{ color: row.score >= 12 ? '#ff5c6c' : '#ffb020', fontWeight: 600 }">
              {{ Number(row.score).toFixed(2) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="问题描述" min-width="360" show-overflow-tooltip>
          <template #default="{ row }">{{ row.description || reasonText(row.reason) }}</template>
        </el-table-column>
        <el-table-column label="轨迹曲线" width="130" align="center">
          <template #default="{ row }">
            <el-tooltip
              v-if="Array.isArray(row.path) && row.path.length >= 2"
              placement="left"
              effect="light"
              :show-after="150"
            >
              <template #content>
                <svg
                  style="width: 280px; height: 156px; background: #f7f9fc; border-radius: 6px"
                  viewBox="0 0 100 56"
                  preserveAspectRatio="none"
                >
                  <polyline
                    :points="svgPolyline(row.path)"
                    fill="none"
                    stroke="#4da3ff"
                    stroke-width="2"
                    stroke-linejoin="round"
                    stroke-linecap="round"
                  />
                  <circle :cx="Number(row.path[0][0]) * 100" :cy="Number(row.path[0][1]) * 56" r="2.5" fill="#37c98a" />
                  <circle
                    :cx="Number(row.path[row.path.length - 1][0]) * 100"
                    :cy="Number(row.path[row.path.length - 1][1]) * 56"
                    r="2.5"
                    fill="#ff5c6c"
                  />
                </svg>
              </template>
              <svg class="mini-path" viewBox="0 0 100 56" preserveAspectRatio="none">
                <polyline
                  :points="svgPolyline(row.path)"
                  fill="none"
                  stroke="#4da3ff"
                  stroke-width="2"
                  stroke-linejoin="round"
                  stroke-linecap="round"
                />
                <circle :cx="Number(row.path[0][0]) * 100" :cy="Number(row.path[0][1]) * 56" r="2.5" fill="#37c98a" />
                <circle
                  :cx="Number(row.path[row.path.length - 1][0]) * 100"
                  :cy="Number(row.path[row.path.length - 1][1]) * 56"
                  r="2.5"
                  fill="#ff5c6c"
                />
              </svg>
            </el-tooltip>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="快照" width="100" align="center">
          <template #default="{ row }">
            <el-image
              v-if="snapshotUrl(row) && !snapErr[row.id]"
              :src="snapshotUrl(row)"
              :preview-src-list="[snapshotUrl(row)]"
              preview-teleported
              fit="cover"
              style="width: 88px; height: 50px; border-radius: 4px"
              @error="snapErr[row.id] = true"
            />
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="时长" width="80" align="center">
          <template #default="{ row }">{{ Number(row.duration_s || 0).toFixed(1) }}s</template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status === 'reviewed' ? 'success' : row.status === 'ignored' ? 'info' : 'warning'" size="small">
              {{ row.status === 'reviewed' ? '已核查' : row.status === 'ignored' ? '已忽略' : '待核查' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" align="center">
          <template #default="{ row }">
            <el-button v-if="row.status === 'pending'" link type="primary" @click="markDeviation(row.id, 'reviewed')">已核查</el-button>
            <el-button v-if="row.status === 'pending'" link type="info" @click="markDeviation(row.id, 'ignored')">忽略</el-button>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 线索池 -->
    <div v-show="tab === 'clues'" class="panel">
      <div class="panel-head">
        <el-button icon="Back" @click="onTab('overview')">返回总览</el-button>
        <span>线索池 · 历史积累</span>
        <el-button link type="primary" icon="Refresh" @click="loadClues">刷新</el-button>
      </div>

      <div class="dev-stats">
        <span>线索总数 <b>{{ clueStats.total || 0 }}</b></span>
        <span>待核查 <b class="dev-hot">{{ clueStats.pending || 0 }}</b></span>
        <span>最高分 <b>{{ Number(clueStats.max_score || 0).toFixed(2) }}</b></span>
      </div>

      <el-table :data="clues" size="small" height="480" stripe>
        <el-table-column label="时间" width="180">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="类型" width="120">
          <template #default="{ row }">{{ clueTypeName(row.clue_type) }}</template>
        </el-table-column>
        <el-table-column label="分数" width="90" align="center">
          <template #default="{ row }">
            <span :style="{ color: row.score >= 10 ? '#ff5c6c' : '#ffb020', fontWeight: 600 }">{{ Number(row.score).toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="evidence_summary" label="线索说明" min-width="420" show-overflow-tooltip />
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status === 'reviewed' ? 'success' : row.status === 'ignored' ? 'info' : 'warning'" size="small">
              {{ row.status === 'reviewed' ? '已核查' : row.status === 'ignored' ? '已忽略' : '待核查' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" align="center">
          <template #default="{ row }">
            <el-button v-if="row.status === 'pending'" link type="primary" @click="markClue(row.id, 'reviewed')">已核查</el-button>
            <el-button v-if="row.status === 'pending'" link type="info" @click="markClue(row.id, 'ignored')">忽略</el-button>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup name="Dashboard">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import * as echarts from 'echarts'

const base = `${location.protocol}//${location.hostname}:8080`
const frigateUrl = `${location.protocol}//${location.hostname}:5000`

const tab = ref('overview')
const clock = ref('')
const stats = ref({ total: 0, active: 0, by_type: [], by_level: [], timeline: [] })
const recentAlarms = ref([])
const alarmItems = ref([])
const alarmTotal = ref(0)
const devStats = ref({ total: 0, pending: 0, reviewed: 0, ignored: 0, max_score: 0, tracks: 0, baselines: 0 })
const deviations = ref([])
const selectedDeviation = ref(null)
const devScoreChartEl = ref(null)
const devPathChartEl = ref(null)
const snapErr = ref({})
const clueStats = ref({ total: 0, pending: 0, reviewed: 0, ignored: 0, max_score: 0 })
const clues = ref([])

const page = ref(1)
const pageSize = ref(50)
const filterType = ref('')
const filterStatus = ref('')

const liveUrl = computed(() => `${base}/api/live.mjpg`)

const statCards = computed(() => {
  const m = {}
  ;(stats.value.by_type || []).forEach((x) => (m[x.event_type] = x.count))
  return [
    { key: 'total', label: '告警总数', value: stats.value.total || 0, color: '#4da3ff' },
    { key: 'active', label: '待处理', value: stats.value.active || 0, color: '#ff5c6c' },
    { key: 'pacing', label: '反复徘徊', value: m.pacing || 0, color: '#ffb020' },
    { key: 'dwell', label: '异常逗留', value: m.abnormal_dwell || 0, color: '#a98bff' },
    { key: 'crowd', label: '人群聚集', value: m.crowd || 0, color: '#37c98a' },
    { key: 'cooccur', label: '共现', value: m.cooccur || 0, color: '#4dd0e1' }
  ]
})

// ---- ECharts ----
const typeChartEl = ref(null)
const levelChartEl = ref(null)
const timeChartEl = ref(null)
const charts = {}
let chartsReady = false

function initCharts() {
  nextTick(() => {
    if (typeChartEl.value && !charts.type) charts.type = echarts.init(typeChartEl.value)
    if (levelChartEl.value && !charts.level) charts.level = echarts.init(levelChartEl.value)
    if (timeChartEl.value && !charts.time) charts.time = echarts.init(timeChartEl.value)
    chartsReady = true
    renderCharts()
    Object.values(charts).forEach((c) => c.resize())
  })
}

function renderCharts() {
  if (!chartsReady) return
  const d = stats.value
  if (charts.type) {
    const items = d.by_type || []
    charts.type.setOption(
      {
        tooltip: { trigger: 'axis' },
        grid: { left: 90, right: 20, top: 16, bottom: 24 },
        xAxis: { type: 'value', axisLabel: { color: '#8a96ab' }, splitLine: { lineStyle: { color: '#eef2f7' } } },
        yAxis: {
          type: 'category',
          data: items.map((x) => x.event_name || x.event_type),
          axisLabel: { color: '#5a6b85' }
        },
        series: [
          {
            type: 'bar',
            data: items.map((x) => x.count),
            barMaxWidth: 16,
            itemStyle: { color: '#4da3ff', borderRadius: [0, 4, 4, 0] }
          }
        ]
      },
      true
    )
  }
  if (charts.level) {
    charts.level.setOption(
      {
        tooltip: { trigger: 'item' },
        legend: { bottom: 0, textStyle: { color: '#5a6b85' } },
        series: [
          {
            type: 'pie',
            radius: ['45%', '70%'],
            center: ['50%', '45%'],
            label: { show: false },
            data: (d.by_level || []).map((x) => ({
              name: x.alert_level,
              value: x.count,
              itemStyle: { color: x.alert_level === 'high' ? '#ff5c6c' : x.alert_level === 'low' ? '#37c98a' : '#ffb020' }
            }))
          }
        ]
      },
      true
    )
  }
  if (charts.time) {
    const t = d.timeline || []
    charts.time.setOption(
      {
        tooltip: { trigger: 'axis' },
        grid: { left: 40, right: 20, top: 16, bottom: 24 },
        xAxis: {
          type: 'category',
          data: t.map((x) => String(x.h).slice(11, 16)),
          axisLabel: { color: '#8a96ab' }
        },
        yAxis: { type: 'value', axisLabel: { color: '#8a96ab' }, splitLine: { lineStyle: { color: '#eef2f7' } } },
        series: [
          {
            type: 'line',
            smooth: true,
            data: t.map((x) => x.count),
            itemStyle: { color: '#37c98a' },
            areaStyle: { color: 'rgba(55,201,138,0.15)' }
          }
        ]
      },
      true
    )
  }
}

// ---- 数据 ----
const timers = []
function fixUrl(u) {
  if (!u) return ''
  if (u.startsWith('/')) return `${base}${u}`
  return u.replace('127.0.0.1', location.hostname).replace('localhost', location.hostname)
}
function fmtTime(t) {
  if (!t) return '-'
  return String(t).replace('T', ' ').slice(0, 19)
}
function levelType(lv) {
  return lv === 'high' ? 'danger' : lv === 'low' ? 'success' : 'warning'
}

async function loadStats() {
  try {
    stats.value = await (await fetch(`${base}/api/stats`)).json()
    renderCharts()
  } catch (e) {
    /* ignore */
  }
}
async function loadRecent() {
  try {
    const d = await (await fetch(`${base}/api/alarms?limit=10`)).json()
    recentAlarms.value = d.items || []
  } catch (e) {
    /* ignore */
  }
}
async function loadAlarms() {
  try {
    const q = new URLSearchParams()
    q.set('limit', String(pageSize.value))
    q.set('offset', String((page.value - 1) * pageSize.value))
    if (filterType.value) q.set('event_type', filterType.value)
    if (filterStatus.value) q.set('status', filterStatus.value)
    const d = await (await fetch(`${base}/api/alarms?${q.toString()}`)).json()
    alarmItems.value = d.items || []
    alarmTotal.value = d.total || 0
  } catch (e) {
    /* ignore */
  }
}
async function loadDeviations() {
  try {
    const [s, d] = await Promise.all([
      fetch(`${base}/api/deviation_stats`).then((r) => r.json()),
      fetch(`${base}/api/deviations?limit=100`).then((r) => r.json())
    ])
    devStats.value = s
    deviations.value = d.items || []
    if (!selectedDeviation.value || !deviations.value.some((x) => x.id === selectedDeviation.value.id)) {
      selectedDeviation.value = deviations.value[0] || null
    }
    renderDevCharts()
  } catch (e) {
    /* ignore */
  }
}
async function markDeviation(id, status) {
  try {
    await fetch(`${base}/api/deviations/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status })
    })
    loadDeviations()
  } catch (e) {
    /* ignore */
  }
}
function reasonText(reason) {
  if (!Array.isArray(reason)) return '-'
  return reason.map((x) => `${x.feature}=${x.value} (z=${x.z})`).join('；')
}
function svgPolyline(path) {
  if (!Array.isArray(path)) return ''
  return path
    .map((p) => `${(Number(p[0]) * 100).toFixed(1)},${(Number(p[1]) * 56).toFixed(1)}`)
    .join(' ')
}
function snapshotUrl(row) {
  return row && row.snapshot ? fixUrl(row.snapshot) : ''
}
function initDevCharts() {
  nextTick(() => {
    if (devScoreChartEl.value && !charts.devScore) charts.devScore = echarts.init(devScoreChartEl.value)
    if (devPathChartEl.value && !charts.devPath) charts.devPath = echarts.init(devPathChartEl.value)
    renderDevCharts()
    Object.values(charts).forEach((c) => c.resize())
  })
}
function renderDevCharts() {
  const list = deviations.value || []
  if (charts.devScore) {
    const pts = list.slice().reverse().map((r) => [fmtTime(r.start_time), Number(r.score) || 0])
    charts.devScore.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: 40, right: 20, top: 20, bottom: 34 },
      xAxis: { type: 'category', data: pts.map((p) => p[0]), axisLabel: { color: '#8a96ab', rotate: 30 } },
      yAxis: { type: 'value', axisLabel: { color: '#8a96ab' }, splitLine: { lineStyle: { color: '#eef2f7' } } },
      series: [{ type: 'line', smooth: true, data: pts.map((p) => p[1]), itemStyle: { color: '#ffb020' }, areaStyle: { color: 'rgba(255,176,32,0.12)' } }]
    }, true)
  }
  if (charts.devPath) {
    const sel = selectedDeviation.value
    const path = sel && Array.isArray(sel.path) ? sel.path : []
    charts.devPath.setOption({
      tooltip: { trigger: 'none' },
      grid: { left: 30, right: 20, top: 20, bottom: 24 },
      xAxis: { type: 'value', min: 0, max: 1, axisLabel: { color: '#8a96ab' }, splitLine: { lineStyle: { color: '#eef2f7' } } },
      yAxis: { type: 'value', inverse: true, min: 0, max: 1, axisLabel: { color: '#8a96ab' }, splitLine: { lineStyle: { color: '#eef2f7' } } },
      series: [{
        type: 'line',
        data: path.map((p) => [p[0], p[1]]),
        smooth: true,
        symbol: 'circle',
        symbolSize: 3,
        lineStyle: { color: '#4da3ff', width: 2 },
        itemStyle: { color: '#4da3ff' },
        markPoint: path.length ? { symbolSize: 8, data: [
          { name: '起点', coord: [path[0][0], path[0][1]], itemStyle: { color: '#37c98a' } },
          { name: '终点', coord: [path[path.length - 1][0], path[path.length - 1][1]], itemStyle: { color: '#ff5c6c' } }
        ] } : undefined
      }]
    }, true)
  }
}
function selectDeviation(row) {
  selectedDeviation.value = row
  renderDevCharts()
}
async function loadClues() {
  try {
    const [s, d] = await Promise.all([
      fetch(`${base}/api/clues/stats`).then((r) => r.json()),
      fetch(`${base}/api/clues?limit=100`).then((r) => r.json())
    ])
    clueStats.value = s
    clues.value = d.items || []
  } catch (e) {
    /* ignore */
  }
}
async function markClue(id, status) {
  try {
    await fetch(`${base}/api/clues/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status })
    })
    loadClues()
  } catch (e) {
    /* ignore */
  }
}
function clueTypeName(t) {
  const m = { deviation_cluster: '偏离聚集', odd_hour: '异常时段', return: '匿名回流', companion: '长期共现' }
  return m[t] || t
}
function onFilter() {
  page.value = 1
  loadAlarms()
}
function onSizeChange() {
  page.value = 1
  loadAlarms()
}
function onTab(t) {
  tab.value = t
  if (t === 'alarms') {
    initCharts()
    loadAlarms()
  }
  if (t === 'deviation') {
    initDevCharts()
    loadDeviations()
  }
  if (t === 'clues') {
    loadClues()
  }
}
function refreshAll() {
  loadStats()
  loadRecent()
  loadAlarms()
}

onMounted(() => {
  refreshAll()
  clock.value = new Date().toLocaleString()
  timers.push(setInterval(() => (clock.value = new Date().toLocaleString()), 1000))
  timers.push(
    setInterval(() => {
      loadStats()
      loadRecent()
      // 只在第 1 页时自动刷新表格，避免浏览历史时被打断
      if (tab.value === 'alarms' && page.value === 1) loadAlarms()
      if (tab.value === 'deviation') loadDeviations()
      if (tab.value === 'clues') loadClues()
    }, 5000)
  )
  window.addEventListener('resize', () => Object.values(charts).forEach((c) => c.resize()))
})
onUnmounted(() => {
  timers.forEach((t) => clearInterval(t))
  Object.values(charts).forEach((c) => c.dispose())
})
</script>

<style scoped>
.mini-path {
  width: 110px;
  height: 56px;
  display: inline-block;
  background: #f7f9fc;
  border: 1px solid #eef2f7;
  border-radius: 4px;
}
.dev-charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 12px;
}
@media (max-width: 1100px) {
  .dev-charts {
    grid-template-columns: 1fr;
  }
}
.dev-stats {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  margin-bottom: 10px;
  font-size: 13px;
  color: #5a6b85;
}
.dev-stats b {
  color: #1b2a4a;
}
.dev-hot {
  color: #ff5c6c !important;
}
.dash {
  padding: 4px 4px 20px;
}
.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px;
  border-radius: 12px;
  background: linear-gradient(120deg, #1b2a4a 0%, #243b63 45%, #2f5a8f 100%);
  color: #fff;
  box-shadow: 0 6px 20px rgba(20, 60, 120, 0.18);
}
.hero-title {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 0.5px;
}
.hero-sub {
  margin-top: 4px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.75);
}
.hero-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.clock {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.85);
}
.stats {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
  margin-top: 14px;
}
.stat {
  background: #fff;
  border: 1px solid #e8edf5;
  border-radius: 10px;
  padding: 12px 14px;
}
.stat-k {
  font-size: 12px;
  color: #8a96ab;
}
.stat-v {
  font-size: 24px;
  font-weight: 700;
  margin-top: 2px;
}
.tabs {
  display: flex;
  gap: 8px;
  margin: 14px 0;
}
.tabs button {
  border: 1px solid #dfe6f0;
  background: #f7f9fc;
  color: #5a6b85;
  border-radius: 8px;
  padding: 7px 18px;
  cursor: pointer;
  font-size: 13px;
}
.tabs button.active {
  background: #2f6bd6;
  border-color: #2f6bd6;
  color: #fff;
}
.grid2 {
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: 14px;
}
@media (max-width: 1100px) {
  .grid2 {
    grid-template-columns: 1fr;
  }
  .stats {
    grid-template-columns: repeat(3, 1fr);
  }
}
.panel {
  background: #fff;
  border: 1px solid #e8edf5;
  border-radius: 12px;
  padding: 12px 14px;
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
  font-size: 13px;
  color: #5a6b85;
  font-weight: 600;
}
.live-img {
  width: 100%;
  display: block;
  border-radius: 8px;
  background: #0b101a;
}
.live-big {
  width: 100%;
  max-height: calc(100vh - 320px);
  object-fit: contain;
  display: block;
  border-radius: 8px;
  background: #0b101a;
}
.feed {
  max-height: 380px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.feed-item {
  border-left: 4px solid #4da3ff;
  background: #f7f9fc;
  border-radius: 6px;
  padding: 8px 10px;
}
.feed-item.high {
  border-left-color: #ff5c6c;
}
.feed-item.medium {
  border-left-color: #ffb020;
}
.feed-item.low {
  border-left-color: #37c98a;
}
.feed-top {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
}
.feed-desc {
  font-size: 12px;
  color: #5a6b85;
  margin-top: 2px;
}
.feed-meta {
  font-size: 11px;
  color: #9aa6ba;
  margin-top: 2px;
}
.charts {
  display: grid;
  grid-template-columns: 1.2fr 1fr 1.6fr;
  gap: 12px;
  margin-bottom: 12px;
}
@media (max-width: 1100px) {
  .charts {
    grid-template-columns: 1fr;
  }
}
.chart-card {
  border: 1px solid #eef2f7;
  border-radius: 10px;
  padding: 8px 10px;
  background: #fbfcfe;
}
.chart-title {
  font-size: 12px;
  color: #8a96ab;
  margin-bottom: 4px;
}
.chart {
  width: 100%;
  height: 200px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
}
.muted {
  color: #9aa6ba;
}
.empty {
  color: #9aa6ba;
  text-align: center;
  padding: 20px;
}
.link {
  color: #2f6bd6;
  text-decoration: none;
}
</style>
