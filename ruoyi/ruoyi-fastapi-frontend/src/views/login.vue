<template>
  <div class="login">
    <el-form ref="loginRef" :model="loginForm" :rules="loginRules" class="login-form">
      <h3 class="title">spacetime-agent</h3>
      <p class="subtitle">时空记忆智能体 · 公共安全监测预警</p>
      <el-form-item prop="username">
        <el-input
          v-model="loginForm.username"
          type="text"
          size="large"
          auto-complete="off"
          placeholder="账号"
        >
          <template #prefix><svg-icon icon-class="user" class="el-input__icon input-icon" /></template>
        </el-input>
      </el-form-item>
      <el-form-item prop="password">
        <el-input
          v-model="loginForm.password"
          type="password"
          size="large"
          auto-complete="off"
          placeholder="密码"
          @keyup.enter="handleLogin"
        >
          <template #prefix><svg-icon icon-class="password" class="el-input__icon input-icon" /></template>
        </el-input>
      </el-form-item>
      <el-form-item prop="code" v-if="captchaEnabled">
        <el-input
          v-model="loginForm.code"
          size="large"
          auto-complete="off"
          placeholder="验证码"
          style="width: 63%"
          @keyup.enter="handleLogin"
        >
          <template #prefix><svg-icon icon-class="validCode" class="el-input__icon input-icon" /></template>
        </el-input>
        <div class="login-code">
          <img :src="codeUrl" @click="getCode" class="login-code-img"/>
        </div>
      </el-form-item>
      <el-checkbox v-model="loginForm.rememberMe" style="margin:0px 0px 25px 0px;">记住密码</el-checkbox>
      <el-form-item style="width:100%;">
        <el-button
          :loading="loading"
          size="large"
          type="primary"
          style="width:100%;"
          @click.prevent="handleLogin"
        >
          <span v-if="!loading">登 录</span>
          <span v-else>登 录 中...</span>
        </el-button>
        <div style="float: right;" v-if="register">
          <router-link class="link-type" :to="'/register'">立即注册</router-link>
        </div>
      </el-form-item>
    </el-form>
    <!--  底部  -->
    <div class="el-login-footer">
      <span>Copyright © 2026 spacetime-agent All Rights Reserved.</span>
    </div>
  </div>
</template>

<script setup>
import { getCodeImg } from "@/api/login";
import Cookies from "js-cookie";
import { encrypt, decrypt } from "@/utils/jsencrypt";
import useUserStore from '@/store/modules/user'

const userStore = useUserStore()
const route = useRoute();
const router = useRouter();
const { proxy } = getCurrentInstance();

const loginForm = ref({
  username: "",
  password: "",
  rememberMe: false,
  code: "",
  uuid: ""
});

const loginRules = {
  username: [{ required: true, trigger: "blur", message: "请输入您的账号" }],
  password: [{ required: true, trigger: "blur", message: "请输入您的密码" }],
  code: [{ required: true, trigger: "change", message: "请输入验证码" }]
};

const codeUrl = ref("");
const loading = ref(false);
// 验证码开关
const captchaEnabled = ref(true);
// 注册开关
const register = ref(false);
const redirect = ref(undefined);

watch(route, (newRoute) => {
    redirect.value = newRoute.query && newRoute.query.redirect;
}, { immediate: true });

function handleLogin() {
  proxy.$refs.loginRef.validate(valid => {
    if (valid) {
      loading.value = true;
      // 勾选了需要记住密码设置在 cookie 中设置记住用户名和密码
      if (loginForm.value.rememberMe) {
        Cookies.set("username", loginForm.value.username, { expires: 30 });
        Cookies.set("password", encrypt(loginForm.value.password), { expires: 30 });
        Cookies.set("rememberMe", loginForm.value.rememberMe, { expires: 30 });
      } else {
        // 否则移除
        Cookies.remove("username");
        Cookies.remove("password");
        Cookies.remove("rememberMe");
      }
      // 调用action的登录方法
      userStore.login(loginForm.value).then(() => {
        const query = route.query;
        const otherQueryParams = Object.keys(query).reduce((acc, cur) => {
          if (cur !== "redirect") {
            acc[cur] = query[cur];
          }
          return acc;
        }, {});
        router.push({ path: redirect.value || "/", query: otherQueryParams });
      }).catch(() => {
        loading.value = false;
        // 重新获取验证码
        if (captchaEnabled.value) {
          getCode();
        }
      });
    }
  });
}

function getCode() {
  getCodeImg().then(res => {
    captchaEnabled.value = res.captchaEnabled === undefined ? true : res.captchaEnabled;
    register.value = res.registerEnabled === undefined ? false : res.registerEnabled;
    if (captchaEnabled.value) {
      codeUrl.value = "data:image/gif;base64," + res.img;
      loginForm.value.uuid = res.uuid;
    }
  });
}

function getCookie() {
  const username = Cookies.get("username");
  const password = Cookies.get("password");
  const rememberMe = Cookies.get("rememberMe");
  loginForm.value = {
    username: username === undefined ? loginForm.value.username : username,
    password: password === undefined ? loginForm.value.password : decrypt(password),
    rememberMe: rememberMe === undefined ? false : Boolean(rememberMe)
  };
}

getCode();
getCookie();
</script>

<style lang='scss' scoped>
.login {
  position: relative;
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
  overflow: hidden;
  background:
    radial-gradient(circle at 18% 18%, rgba(77, 163, 255, 0.18), transparent 42%),
    radial-gradient(circle at 82% 82%, rgba(55, 201, 138, 0.12), transparent 42%),
    linear-gradient(135deg, #060b14 0%, #0b1424 45%, #0a1a2e 100%);

  &::before {
    content: "";
    position: absolute;
    inset: 0;
    background-image:
      linear-gradient(rgba(77, 163, 255, 0.08) 1px, transparent 1px),
      linear-gradient(90deg, rgba(77, 163, 255, 0.08) 1px, transparent 1px);
    background-size: 48px 48px;
    mask-image: radial-gradient(circle at center, rgba(0, 0, 0, 0.9), transparent 78%);
    pointer-events: none;
  }

  &::after {
    content: "";
    position: absolute;
    width: 680px;
    height: 680px;
    right: -180px;
    top: -180px;
    border-radius: 50%;
    border: 1px solid rgba(77, 163, 255, 0.16);
    box-shadow: 0 0 140px rgba(77, 163, 255, 0.10) inset;
    pointer-events: none;
  }
}
.title {
  margin: 0 auto 6px;
  text-align: center;
  color: #e8f1ff;
  font-size: 28px;
  font-weight: 700;
  letter-spacing: 1.5px;
  text-shadow: 0 0 20px rgba(77, 163, 255, 0.55);
}
.subtitle {
  margin: 0 0 26px;
  text-align: center;
  color: #7f93b0;
  font-size: 12px;
  letter-spacing: 2px;
}

.login-form {
  position: relative;
  z-index: 2;
  width: 400px;
  padding: 28px 28px 8px;
  border-radius: 14px;
  background: rgba(15, 23, 42, 0.78);
  border: 1px solid rgba(77, 163, 255, 0.22);
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.55), 0 0 0 1px rgba(77, 163, 255, 0.05) inset;
  backdrop-filter: blur(14px);

  .el-input {
    height: 42px;
    input {
      height: 42px;
    }
  }
  .input-icon {
    height: 39px;
    width: 14px;
    margin-left: 0px;
    color: #7fb2ff;
  }

  :deep(.el-input__wrapper) {
    background: rgba(255, 255, 255, 0.06);
    box-shadow: 0 0 0 1px rgba(77, 163, 255, 0.18) inset;
    border-radius: 8px;
  }
  :deep(.el-input__inner) {
    color: #e8f1ff;
  }
  :deep(.el-input__inner::placeholder) {
    color: #6b7a94;
  }
  :deep(.el-input__prefix) {
    color: #7fb2ff;
  }
  :deep(.el-checkbox__label) {
    color: #9fb0c9;
  }
  :deep(.el-checkbox__input.is-checked .el-checkbox__inner) {
    background-color: #2f6bd6;
    border-color: #2f6bd6;
  }
  :deep(.el-button--primary) {
    background: linear-gradient(90deg, #2f6bd6, #4da3ff);
    border: none;
    letter-spacing: 4px;
    font-weight: 600;
    box-shadow: 0 8px 24px rgba(47, 107, 214, 0.35);
  }
}
.login-tip {
  font-size: 13px;
  text-align: center;
  color: #bfbfbf;
}
.login-code {
  width: 33%;
  height: 40px;
  float: right;
  img {
    cursor: pointer;
    vertical-align: middle;
  }
}
.el-login-footer {
  height: 40px;
  line-height: 40px;
  position: fixed;
  bottom: 0;
  width: 100%;
  text-align: center;
  color: rgba(255, 255, 255, 0.55);
  font-family: Arial;
  font-size: 12px;
  letter-spacing: 1px;
  z-index: 2;
}
.login-code-img {
  height: 40px;
  padding-left: 12px;
  border-radius: 6px;
}
</style>
