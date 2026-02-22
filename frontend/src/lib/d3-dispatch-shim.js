/**
 * ESM shim for d3-dispatch when the package is missing src/dispatch.js.
 * Source: d3-dispatch v3.0.1 (https://github.com/d3/d3-dispatch)
 */
const noop = { value: () => {} }

function dispatch() {
  let i = 0
  const n = arguments.length
  const _ = {}
  let t
  for (; i < n; ++i) {
    t = arguments[i] + ''
    if (!t || t in _ || /[\s.]/.test(t)) throw new Error('illegal type: ' + t)
    _[t] = []
  }
  return new Dispatch(_)
}

function Dispatch(_) {
  this._ = _
}

function parseTypenames(typenames, types) {
  return typenames.trim().split(/^|\s+/).map(function (t) {
    let name = ''
    const i = t.indexOf('.')
    if (i >= 0) {
      name = t.slice(i + 1)
      t = t.slice(0, i)
    }
    if (t && !Object.prototype.hasOwnProperty.call(types, t)) throw new Error('unknown type: ' + t)
    return { type: t, name }
  })
}

function get(type, name) {
  for (let i = 0, n = type.length, c; i < n; ++i) {
    if ((c = type[i]).name === name) return c.value
  }
}

function set(type, name, callback) {
  for (let i = 0, n = type.length; i < n; ++i) {
    if (type[i].name === name) {
      type[i] = noop
      type = type.slice(0, i).concat(type.slice(i + 1))
      break
    }
  }
  if (callback != null) type.push({ name, value: callback })
  return type
}

Dispatch.prototype = dispatch.prototype = {
  constructor: Dispatch,
  on(typename, callback) {
    const _ = this._
    const T = parseTypenames(typename + '', _)
    let t
    let i = -1
    const n = T.length
    if (arguments.length < 2) {
      while (++i < n) if ((t = (typename = T[i]).type) && (t = get(_[t], typename.name))) return t
      return
    }
    if (callback != null && typeof callback !== 'function') throw new Error('invalid callback: ' + callback)
    while (++i < n) {
      if ((t = (typename = T[i]).type)) _[t] = set(_[t], typename.name, callback)
      else if (callback == null) for (t in _) _[t] = set(_[t], typename.name, null)
    }
    return this
  },
  copy() {
    const copy = {}
    const _ = this._
    for (const t in _) copy[t] = _[t].slice()
    return new Dispatch(copy)
  },
  call(type, that) {
    let n = arguments.length - 2
    let args
    if (n > 0) {
      args = new Array(n)
      for (let i = 0; i < n; ++i) args[i] = arguments[i + 2]
    }
    if (!Object.prototype.hasOwnProperty.call(this._, type)) throw new Error('unknown type: ' + type)
    for (let t = this._[type], i = 0, nn = t.length; i < nn; ++i) t[i].value.apply(that, n > 0 ? args : [])
  },
  apply(type, that, args) {
    if (!Object.prototype.hasOwnProperty.call(this._, type)) throw new Error('unknown type: ' + type)
    for (let t = this._[type], i = 0, n = t.length; i < n; ++i) t[i].value.apply(that, args)
  },
}

export { dispatch }
export default dispatch
