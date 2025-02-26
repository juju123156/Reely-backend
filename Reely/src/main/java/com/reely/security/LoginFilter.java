package com.reely.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.reely.dto.MemberDto;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletInputStream;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.util.StreamUtils;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Collection;
import java.util.Iterator;

@Slf4j
public class LoginFilter extends UsernamePasswordAuthenticationFilter {

    private final AuthenticationManager authenticationManager;
    private final JWTUtil jwtUtil;

    private  final CustomAuthenticationFailureHandler failureHandler;
    private final ObjectMapper objectMapper = new ObjectMapper();
    public LoginFilter(AuthenticationManager authenticationManager, JWTUtil jwtUtil, CustomAuthenticationFailureHandler failureHandler) {
        this.authenticationManager = authenticationManager;
        this.jwtUtil = jwtUtil;
        this.failureHandler = failureHandler;
        this.setFilterProcessesUrl("/api/auth/login");
    }

    @Override
    public Authentication attemptAuthentication(HttpServletRequest request, HttpServletResponse response) throws AuthenticationException {

        log.info("================== loginFilter 시작 ===================");

        // JSON 형식으로 받은 데이터 파싱
        MemberDto memberDto  = new MemberDto();

        try {
            ServletInputStream inputStream = request.getInputStream();
            String messageBody = StreamUtils.copyToString(inputStream, StandardCharsets.UTF_8);
            memberDto = objectMapper.readValue(messageBody, MemberDto.class);

        } catch (IOException e) {
            throw new RuntimeException(e);
        }

        log.info("memberId={}", memberDto.getMemberId());
        log.info("memberPwd={}", memberDto.getMemberPwd());

        String memberId = memberDto.getMemberId();
        String memberPwd = memberDto.getMemberPwd();

        UsernamePasswordAuthenticationToken authToken = new UsernamePasswordAuthenticationToken(memberId, memberPwd, null);
        log.info("authToken={}", authToken);
        // AuthenticationManager를 사용하여 인증 진행
        return authenticationManager.authenticate(authToken);
    }

    @Override
    protected void successfulAuthentication(HttpServletRequest request, HttpServletResponse response, FilterChain chain, Authentication authentication) {
        //유저 정보
        String username = authentication.getName();

        Collection<? extends GrantedAuthority> authorities = authentication.getAuthorities();
        Iterator<? extends GrantedAuthority> iterator = authorities.iterator();
        GrantedAuthority auth = iterator.next();
        String role = auth.getAuthority();

        //토큰 생성
        String access = jwtUtil.createJwt("access", username, role, 600000L);
        String refresh = jwtUtil.createJwt("refresh", username, role, 86400000L);

        //토큰 (테스트)저장
        // access >  Secure Storage 저장으로 수정
        // refresh > redis 저장
        response.setHeader("access", access);
        response.addCookie(createCookie("refresh", refresh));
        response.setStatus(HttpStatus.OK.value());
    }

    private Cookie createCookie(String key, String value) {

        Cookie cookie = new Cookie(key, value);
        cookie.setMaxAge(24*60*60);
        //cookie.setSecure(true);
        //cookie.setPath("/");
        cookie.setHttpOnly(true);

        return cookie;
    }

    @Override
    protected void unsuccessfulAuthentication(HttpServletRequest request, HttpServletResponse response, AuthenticationException failed) throws IOException {
        log.info("token 발급 실패");
        failureHandler.onAuthenticationFailure(request, response, failed);
    }
}
