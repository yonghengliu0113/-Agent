/**
 * 类型统一出口。
 * 旧代码继续从 `@/types/api` 导入即可；实际结构已按业务域拆分到本目录下多个文件，
 * 这样既能控制单文件体积，又不改动任何引用点与接口契约。
 */

export type * from './common'
export type * from './chat'
export type * from './customer'
export type * from './evaluation'
export type * from './monitor'
export type * from './order'
export type * from './staff'
export type * from './ticket'
