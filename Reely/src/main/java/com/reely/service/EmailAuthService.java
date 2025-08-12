package com.reely.service;

import com.reely.dto.EmailDto;

public interface EmailAuthService {
    void sendAuthCode(EmailDto emailDto);

    boolean verifyAuthCode(EmailDto emailDto);
}
