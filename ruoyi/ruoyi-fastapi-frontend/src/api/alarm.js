import request from '@/utils/request'

// 告警分页列表（module_alarm）
export function listAlarm(params) {
  return request({
    url: '/alarm/alarm/list',
    method: 'get',
    params: params
  })
}
