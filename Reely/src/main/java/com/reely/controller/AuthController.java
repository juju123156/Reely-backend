package com.reely.controller;

import com.reely.common.enums.SMSAuthType;
import com.reely.dto.EmailDto;
import com.reely.dto.MemberDto;
import com.reely.dto.ResponseDto;
import com.reely.dto.TokenDto;
import com.reely.exception.CustomException;
import com.reely.exception.ErrorCode;
import com.reely.security.JWTUtil;
import com.reely.security.TokenConstants;
import com.reely.service.AuthService;
import com.reely.service.EmailAuthService;
import com.reely.service.MemberService;
import jakarta.servlet.http.Cookie;

import jakarta.validation.Valid;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;


@Controller
@Slf4j
@RequestMapping("/api/auth")
public class AuthController {
    private final JWTUtil jwtUtil;

    private final AuthService authService;

    private final EmailAuthService emailAuthService;

    private final MemberService memberService;


    public AuthController(JWTUtil jwtUtil, AuthService authService, EmailAuthService emailAuthService, MemberService memberService) {
        this.jwtUtil = jwtUtil;
        this.authService = authService;
        this.emailAuthService = emailAuthService;
        this.memberService = memberService;
    }

    @PostMapping("/reissue")
    public ResponseEntity<ResponseDto<?>> reissue(@RequestBody TokenDto resTokenDto) {
        //get refresh token
        String refresh = resTokenDto.getRefreshToken();

        // 토큰 유효성 체크
        if (!jwtUtil.isValid(refresh, TokenConstants.TOKEN_TYPE_REFRESH)) {
            log.info("[ERROR] refresh token is not valid");
            throw new CustomException(ErrorCode.UNAUTHORIZED);
        }

        String username = jwtUtil.getUsername(refresh);
        String role = jwtUtil.getRole(refresh);
        Long memberPk = jwtUtil.getMemberPk(refresh);

        // refresh 토큰이 db에 존재하는지 확인
        if (!authService.isExistRefreshToken(username)) {
            log.info("[ERROR] refresh token is not exist");
            throw new CustomException(ErrorCode.UNAUTHORIZED);
        }

        // 토큰 발급
        String newAccess = jwtUtil.createJwt(TokenConstants.TOKEN_TYPE_ACCESS, username, role, TokenConstants.ACCESS_TOKEN_EXPIRATION, memberPk);
        String newRefresh = jwtUtil.createJwt(TokenConstants.TOKEN_TYPE_REFRESH, username, role, TokenConstants.REFRESH_TOKEN_EXPIRATION, memberPk);

        // 기존 refresh 삭제 처리
        authService.deleteRefreshToken(username);

        // refresh > redis 저장
        authService.saveRefreshToken(username, newRefresh, TokenConstants.REFRESH_TOKEN_EXPIRATION);

        TokenDto tokenDto = TokenDto.builder()
                .accessToken(newAccess)
                .refreshToken(newRefresh)
                .build();

        return ResponseEntity.ok(
                ResponseDto.builder()
                        .success(true)
                        .message("토큰이 발급되었습니다.")
                        .data(tokenDto)
                        .build()
        );
    }

    //@PostMapping("/logout")
    private Cookie createCookie(String key, String value) {

        Cookie cookie = new Cookie(key, value);
        cookie.setMaxAge(24 * 60 * 60);
        //cookie.setSecure(true);
        //cookie.setPath("/");
        cookie.setHttpOnly(true);

        return cookie;
    }

    @PostMapping("/email/send/{authType}")
    public ResponseEntity<ResponseDto<?>> sendAuthCode(@PathVariable String authType, @Valid @RequestBody EmailDto emailDto) {
        emailDto.setAuthType(SMSAuthType.from(authType));

        emailAuthService.sendAuthCode(emailDto);
        return ResponseEntity.ok(
                ResponseDto.builder()
                        .success(true)
                        .message("인증 메일을 전송했습니다.")
                        .build()
        );
    }

    @PostMapping("/email/verify/{authType}")
    public ResponseEntity<ResponseDto<?>> verifyAuthCode(@PathVariable String authType, @Valid @RequestBody EmailDto emailDto) {
        SMSAuthType smsAuthType = SMSAuthType.from(authType);
        emailDto.setAuthType(smsAuthType);

        boolean result = emailAuthService.verifyAuthCode(emailDto);

        if (!result) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                    .body(ResponseDto.builder()
                            .success(false)
                            .message("인증에 실패했습니다.")
                            .errorCode(ErrorCode.UNAUTHORIZED)
                            .build());
        }

        // 인증 성공 시 Builder 생성
        ResponseDto.ResponseDtoBuilder<Object> builder = ResponseDto.builder()
                .success(true)
                .message("인증이 완료되었습니다.");

        // FIND_ID일 경우 data 추가
        if (smsAuthType == SMSAuthType.FIND_ID) {
            MemberDto memberDto = memberService.findMemberIdByMemberEmail(emailDto);
            builder.data(memberDto);
        }

        return ResponseEntity.ok(builder.build());
    }
}
