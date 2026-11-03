# 给 Dev-C++ 5.11 的「插入 → 代码片段」(codeinsertion.ini) 增加 C 语言常用片段。
# 格式: [名字] / Desc=描述 / Line=内容（$_ 换行, *|* 光标落点）/ Sep=分组
# 编码: Dev-C++ 5.11 按系统 ANSI(GBK) 读这个文件，所以用 gbk 写入。
import io
import os
import shutil

INI = os.path.join(os.environ.get("APPDATA", ""), "Dev-Cpp", "codeinsertion.ini")
MARK = "# ---- ccode additions ----"

SNIPPETS = [
    ("C_Main", "C 程序框架", "#include <stdio.h>$__$int main(void) {$__    *|*$__    return 0;$__}"),
    ("C_HeaderBlock", "常用头文件三件套", "#include <stdio.h>$__#include <stdlib.h>$__#include <string.h>$__"),
    ("C_ForLoop", "for 循环（C99 写法）", "for (int i = 0; i < *|*; i++) {$__    $__}"),
    ("C_ArrayInput", "数组输入 n 个元素", "int n;$__scanf(\"%d\", &n);$__for (int i = 0; i < n; i++) {$__    scanf(\"%d\", &a[i]);$__}"),
    ("C_ArrayOutput", "数组输出", "for (int i = 0; i < n; i++) {$__    printf(\"%d \", a[i]);$__}$__printf(\"\\n\");"),
    ("C_MallocCheck", "malloc 并判空", "int *p = (int *)malloc(n * sizeof(int));$__if (p == NULL) {$__    printf(\"内存分配失败\\n\");$__    return 1;$__}"),
    ("C_FileWrite", "写文件", "FILE *fp = fopen(\"*|*\", \"w\");$__if (fp == NULL) {$__    perror(\"打开文件失败\");$__    return 1;$__}$__fprintf(fp, \"%d\\n\", x);$__fclose(fp);"),
    ("C_FileRead", "读文件", "FILE *fp = fopen(\"*|*\", \"r\");$__if (fp == NULL) {$__    perror(\"打开文件失败\");$__    return 1;$__}$__while (fscanf(fp, \"%d\", &x) == 1) {$__    $__}$__fclose(fp);"),
    ("C_Struct", "结构体定义", "typedef struct {$__    char name[32];$__    int score;$__} *|*;"),
    ("C_BubbleSort", "冒泡排序", "void bubbleSort(int a[], int n) {$__    for (int i = 0; i < n - 1; i++) {$__        for (int j = 0; j < n - 1 - i; j++) {$__            if (a[j] > a[j + 1]) {$__                int t = a[j]; a[j] = a[j + 1]; a[j + 1] = t;$__            }$__        }$__    }$__}"),
    ("C_Function", "函数定义模板", "int *|*(int x) {$__    return 0;$__}"),
    ("C_Swap", "交换两个变量", "int t = a; a = b; b = t;"),
    ("C_MatrixLoop", "二维数组遍历", "for (int i = 0; i < row; i++) {$__    for (int j = 0; j < col; j++) {$__        $__    }$__}"),
    ("C_StrCmp", "字符串比较", "if (strcmp(s1, s2) == 0) {$__    $__}"),
    ("C_WhileRead", "while 循环读入直到 EOF", "while (scanf(\"%d\", &x) != EOF) {$__    $__}"),
    ("C_LinkedList", "链表节点 + 头插", "typedef struct Node {$__    int data;$__    struct Node *next;$__} Node;$__Node *head = NULL;$__Node *p = (Node *)malloc(sizeof(Node));$__p->data = *|*;$__p->next = head;$__head = p;"),
    ("C_FactRecursion", "递归求阶乘", "long long fact(int n) {$__    return n <= 1 ? 1 : n * fact(n - 1);$__}"),
    ("C_SwitchMenu", "菜单 switch", "int choice;$__scanf(\"%d\", &choice);$__switch (choice) {$__case 1:$__    $__break;$__default:$__    break;$__}"),
]


def main():
    if not os.environ.get("APPDATA") or not os.path.isfile(INI):
        raise SystemExit(
            "找不到 Dev-C++ 的配置文件：%s\n"
            "请确认已安装 Dev-C++ 并至少启动过一次。" % INI)
    with io.open(INI, "r", encoding="gbk", errors="replace") as f:
        text = f.read()

    if MARK in text:
        print("已追加过，跳过（如需重刷请先还原 .bak-ccode）")
        return 0

    block = [MARK]
    for name, desc, line in SNIPPETS:
        block.append("")
        block.append("[%s]" % name)
        block.append("Desc=%s" % desc)
        block.append("Line=%s" % line)
        block.append("Sep=2")
    if not text.endswith("\n"):
        text += "\r\n"
    text += "\r\n".join(block) + "\r\n"

    with io.open(INI, "w", encoding="gbk", newline="") as f:
        f.write(text)
    print("已写入 %d 个 C 片段 -> %s" % (len(SNIPPETS), INI))
    print("原始备份: %s.bak-ccode" % INI)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
