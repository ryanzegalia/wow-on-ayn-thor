#!/usr/bin/env python3
"""FFEXT fault trace: catch the fault on the big-stack compile thread and log WHERE it is.

Why (2026-09-22): with mkpatch_ffext_bigstack.py (16 MB compile thread) the DXVK -13s
vanished, id=383 got past ir3_nir_lower_variant for the first time, and then the whole
Wine process died (GameNative: "terminated with status: 137") with six of the large
fragment shaders compiling concurrently.  The helper thread has no Wine TEB, so Wine's
process-wide SIGSEGV handler kills the process and nothing is learned.

This installs a SIGSEGV/SIGBUS handler (process-wide sigaction, but it PASSES THROUGH to
the previous handler unless the faulting thread is one of the helper threads, flagged
via a thread-local).  Each helper thread gets a sigaltstack so the handler also runs on a stack
overflow.  On a fault it logs (tag TU, prefix `FFEXT FAULT`):
  sig, si_addr, pc, sp, the .so base and pc offset (symbolise offline with
  llvm-symbolizer against the unstripped build .so), the thread's stack base/size and
  sp-base (a few KB = stack overflow), and a frame-pointer backtrace as lib+offset.
Then it restores the previous handler and returns so the fault re-raises into Wine
exactly as before (the process still dies, the trace just comes first).

Also: FFEXT_BIGSTACK=<MB> now sets the helper stack size (default 16; "0" = inline).

usage: mkpatch_ffext_faulttrace.py <mesa_src_root>   (idempotent)
Requires mkpatch_ffext_bigstack.py.
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1])
tu_shader = root / "src/freedreno/vulkan/tu_shader.cc"
MARK = "FFEXT fault trace"

t = tu_shader.read_text()
if MARK in t:
    print("  tu_shader.cc: fault trace already present")
    sys.exit(0)

old_thread_fn = """static void *
ffext_variant_thread(void *p)
{
   struct ffext_variant_job *j = (struct ffext_variant_job *)p;
   j->out = ir3_shader_create_variant(j->shader, j->key, j->executable_info);
   return NULL;
}
"""
new_thread_fn = """/* ---- FFEXT fault trace ---------------------------------------------------- */
#include <signal.h>
#include <ucontext.h>
#include <dlfcn.h>
#include <unistd.h>
#include <android/log.h>
static __thread int ffext_in_helper;
static struct sigaction ffext_old_sa[2]; /* [0]=SIGSEGV [1]=SIGBUS */
static int ffext_handler_installed;

#define FFEXT_LOG(...) __android_log_print(ANDROID_LOG_ERROR, "TU", __VA_ARGS__)

static void
ffext_fault_handler(int sig, siginfo_t *si, void *uc_)
{
   struct sigaction *old = &ffext_old_sa[sig == SIGBUS ? 1 : 0];
   if (!ffext_in_helper) {
      /* not this handler's thread: behave exactly like the previous handler */
      if (old->sa_flags & SA_SIGINFO) {
         old->sa_sigaction(sig, si, uc_);
      } else if (old->sa_handler == SIG_DFL || old->sa_handler == SIG_IGN) {
         sigaction(sig, old, NULL); /* re-raise on return */
      } else {
         old->sa_handler(sig);
      }
      return;
   }
   ucontext_t *uc = (ucontext_t *)uc_;
   uintptr_t pc = (uintptr_t)uc->uc_mcontext.pc;
   uintptr_t sp = (uintptr_t)uc->uc_mcontext.sp;
   uintptr_t fp = (uintptr_t)uc->uc_mcontext.regs[29];
   uintptr_t lr = (uintptr_t)uc->uc_mcontext.regs[30];
   Dl_info di;
   uintptr_t mybase = 0;
   if (dladdr((void *)&ffext_fault_handler, &di))
      mybase = (uintptr_t)di.dli_fbase;
   FFEXT_LOG("FFEXT FAULT sig=%d code=%d addr=%p pc=0x%lx lr=0x%lx sp=0x%lx fp=0x%lx "
             "turnip_base=0x%lx pc_off=0x%lx lr_off=0x%lx", sig, si->si_code, si->si_addr,
             (unsigned long)pc, (unsigned long)lr, (unsigned long)sp, (unsigned long)fp,
             (unsigned long)mybase, (unsigned long)(pc - mybase), (unsigned long)(lr - mybase));
   pthread_attr_t at;
   void *sbase = NULL; size_t ssize = 0;
   if (pthread_getattr_np(pthread_self(), &at) == 0) {
      pthread_attr_getstack(&at, &sbase, &ssize);
      pthread_attr_destroy(&at);
      FFEXT_LOG("FFEXT FAULT stack base=%p size=%zu sp-base=%ld (small => stack overflow)",
                sbase, ssize, (long)(sp - (uintptr_t)sbase));
   }
   /* frame-pointer walk: aarch64 frame = [fp] = prev fp, [fp+8] = return addr */
   uintptr_t lo = (uintptr_t)sbase, hi = (uintptr_t)sbase + ssize;
   uintptr_t cur = fp;
   for (int i = 0; i < 48; i++) {
      if (cur < lo || cur + 16 > hi || (cur & 7))
         break;
      uintptr_t ret = *(uintptr_t *)(cur + 8);
      uintptr_t prev = *(uintptr_t *)cur;
      Dl_info d2;
      const char *nm = "?";
      uintptr_t fb = 0;
      if (dladdr((void *)ret, &d2)) {
         nm = d2.dli_fname ? d2.dli_fname : "?";
         fb = (uintptr_t)d2.dli_fbase;
      }
      const char *base = nm;
      for (const char *q = nm; *q; q++) if (*q == '/') base = q + 1;
      FFEXT_LOG("FFEXT FAULT #%02d ret=0x%lx %s+0x%lx", i, (unsigned long)ret, base,
                (unsigned long)(ret - fb));
      if (prev <= cur)
         break;
      cur = prev;
   }
   FFEXT_LOG("FFEXT FAULT end -- handing the fault back to the previous handler");
   sigaction(sig, old, NULL); /* restore; returning re-executes the faulting insn */
}

static void
ffext_install_fault_handler(void)
{
   if (ffext_handler_installed)
      return;
   ffext_handler_installed = 1;
   struct sigaction sa;
   memset(&sa, 0, sizeof(sa));
   sa.sa_sigaction = ffext_fault_handler;
   sa.sa_flags = SA_SIGINFO | SA_ONSTACK | SA_NODEFER;
   sigemptyset(&sa.sa_mask);
   sigaction(SIGSEGV, &sa, &ffext_old_sa[0]);
   sigaction(SIGBUS, &sa, &ffext_old_sa[1]);
   FFEXT_LOG("FFEXT fault handler installed (prev segv=%p bus=%p)",
             (void *)ffext_old_sa[0].sa_sigaction, (void *)ffext_old_sa[1].sa_sigaction);
}

static void *
ffext_variant_thread(void *p)
{
   struct ffext_variant_job *j = (struct ffext_variant_job *)p;
   /* alternate signal stack so the handler runs even after a stack overflow */
   stack_t ss;
   ss.ss_size = 256 * 1024;
   ss.ss_sp = malloc(ss.ss_size);
   ss.ss_flags = 0;
   if (ss.ss_sp)
      sigaltstack(&ss, NULL);
   ffext_in_helper = 1;
   j->out = ir3_shader_create_variant(j->shader, j->key, j->executable_info);
   ffext_in_helper = 0;
   if (ss.ss_sp) {
      stack_t off; off.ss_flags = SS_DISABLE; off.ss_sp = NULL; off.ss_size = 0;
      sigaltstack(&off, NULL);
      free(ss.ss_sp);
   }
   return NULL;
}
"""
if t.count(old_thread_fn) != 1:
    sys.exit("bigstack thread function anchor not found; apply mkpatch_ffext_bigstack.py first")
t = t.replace(old_thread_fn, new_thread_fn)

old_size = """   const char *e = getenv("FFEXT_BIGSTACK");
   if (e && e[0] == '0')
      return ir3_shader_create_variant(shader, key, executable_info);

   struct ffext_variant_job j = { shader, key, executable_info, NULL };
   pthread_attr_t attr;
   pthread_t th;
   pthread_attr_init(&attr);
   pthread_attr_setstacksize(&attr, (size_t)16 << 20);
"""
new_size = """   const char *e = getenv("FFEXT_BIGSTACK");
   size_t mb = 16;
   if (e && e[0]) {
      mb = (size_t)atoi(e);
      if (mb == 0)
         return ir3_shader_create_variant(shader, key, executable_info);
   }
   ffext_install_fault_handler();

   struct ffext_variant_job j = { shader, key, executable_info, NULL };
   pthread_attr_t attr;
   pthread_t th;
   pthread_attr_init(&attr);
   pthread_attr_setstacksize(&attr, mb << 20);
"""
if t.count(old_size) != 1:
    sys.exit("bigstack size anchor not found")
t = t.replace(old_size, new_size)
if "#include <string.h>" not in t:
    t = t.replace("#include <pthread.h>\n#include <stdlib.h>\n", "#include <pthread.h>\n#include <stdlib.h>\n#include <string.h>\n", 1)
t = t.replace("/* FFEXT bigstack: run the ir3 compile", f"/* {MARK} + FFEXT bigstack: run the ir3 compile", 1)
tu_shader.write_text(t)
print("  tu_shader.cc: fault handler + altstack + FFEXT_BIGSTACK=<MB> installed")
print("done")
