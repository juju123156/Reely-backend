package com.reely.serviceImpl;

import com.reely.dto.EmailDto;
import com.reely.exception.CustomException;
import com.reely.exception.ErrorCode;
import com.reely.service.AuthService;
import com.reely.service.EmailAuthService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.mail.MailException;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.stereotype.Service;

@Service
@Slf4j
public class EmailAuthServiceImpl implements EmailAuthService {
    private final AuthService authService;
    private final JavaMailSender javaMailSender;

    public EmailAuthServiceImpl(AuthService authService, JavaMailSender javaMailSender) {
        this.authService = authService;
        this.javaMailSender = javaMailSender;
    }

    private static final long EXPIRE_SECONDS = 300; // 5분

    @Override
    public void sendAuthCode(EmailDto emailDto) {
        String code = generateCode();

        try {
            // todo 전송 메시지 html 적용하기
            SimpleMailMessage message = new SimpleMailMessage();
            message.setTo(emailDto.getEmail());
            message.setSubject("이메일 인증번호");
            message.setText("인증번호는 " + code + " 입니다. 5분 이내에 사용하세요.");
            javaMailSender.send(message);

            // Redis에 저장
            authService.saveEmailAuthCode(emailDto.getEmail(), code, EXPIRE_SECONDS);

        } catch (MailException e) {
            throw new CustomException(ErrorCode.INTERNAL_ERROR, "메일 전송에 실패했습니다.");
        }
    }

    @Override
    public boolean verifyAuthCode(EmailDto emailDto) {
        String savedCode = authService.getEmailAuthCode(emailDto.getEmail());
        if (savedCode == null) {
            log.info("인증번호가 만료되었거나 존재하지 않습니다. emailDto.getEmail()={}", emailDto.getEmail());
            return false;
        }
        boolean matched = savedCode.equals(emailDto.getCode());
        if (matched) {
            // 검증 완료 후 인증번호 삭제
            authService.deleteEmailAuthCode(emailDto.getEmail());
            log.info("이메일 인증 성공. emailDto.getEmail()={}", emailDto.getEmail());
        } else {
            log.info("이메일 인증 실패. emailDto.getEmail()={}, emailDto.getCode()={}, saved={}", emailDto.getEmail(), emailDto.getCode(), savedCode);
        }
        return matched;
    }

    // 인증번호 생성 (6자리 숫자)
    private String generateCode() {
        int code = (int) (Math.random() * 900000) + 100000;
        return String.valueOf(code);
    }
}
