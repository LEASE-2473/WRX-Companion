const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const src = fs.readFileSync('app/static/chat-ui.js', 'utf8');
const document = {createElement(tag){return {tag,children:[],append(...nodes){this.children.push(...nodes)},replaceChildren(){this.children=[]}}},createTextNode(text){return {text}}};
const ctx = vm.createContext({document});
vm.runInContext(src.slice(src.indexOf('const NEXT_MESSAGE'), src.indexOf('const baseMessageNode')),ctx);
for(let n=1;n<'<|next_message|>'.length;n++) {
 assert.equal(vm.runInContext(`splitReplyMessages('第一条'+NEXT_MESSAGE.slice(0,${n}),true).join('')`,ctx),'第一条');
}
ctx.node = document.createElement('div');
vm.runInContext("renderMessageText(node, '第一条<|next_message|>第二条', true)",ctx);
assert.equal(ctx.node.children.length,2);
assert.equal(ctx.node.children[0].children[0].children[0].text,'第一条');
vm.runInContext("renderMessageText(node, '用户写的<|next_message|>例子', false)",ctx);
assert.equal(ctx.node.children.length,1);
console.log('分块、所有标记分片、用户正文保留验证通过');
