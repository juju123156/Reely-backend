package com.reely.controller;

import com.reely.exception.ErrorCode;
import com.reely.dto.MemberDto;
import com.reely.dto.ResponseDto;
import com.reely.exception.CustomException;
import com.reely.security.CustomUserDetails;
import com.reely.service.MemberService;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/member")
public class MemberController {

    private final MemberService memberService;

    @Autowired
    public MemberController(MemberService memberService) {
        this.memberService = memberService;
    }

    @PostMapping("/duplicate-id")
    public ResponseEntity<ResponseDto<Boolean>> duplicateId(@RequestBody MemberDto memberDto) {
        Boolean result = memberService.existsByMemberId(memberDto);
        return ResponseEntity.ok(
                ResponseDto.<Boolean>builder()
                        .success(true)
                        .data(result)
                        .build()
        );
    }

    @PostMapping("/join")
    public ResponseEntity<ResponseDto<Integer>> join(@Valid @RequestBody MemberDto memberDto) {
        try {
            Integer result = memberService.insertMember(memberDto);
            return ResponseEntity.ok(
                    ResponseDto.<Integer>builder()
                            .success(true)
                            .data(result)
                            .build()
            );
        } catch (DuplicateKeyException e) {
            throw new CustomException(ErrorCode.USER_ALREADY_EXISTS);
        }
    }

    @PostMapping("/duplicate-email")
    public ResponseEntity<ResponseDto<Boolean>> duplicateEmail(@RequestBody MemberDto memberDto) {
        Boolean result = memberService.existsByMemberEmail(memberDto);
        return ResponseEntity.ok(
                ResponseDto.<Boolean>builder()
                        .success(true)
                        .data(result)
                        .build()
        );
    }

    @PostMapping("/reset-pwd")
    public ResponseEntity<ResponseDto<Boolean>> resetPwd(@RequestBody MemberDto memberDto) {
        Boolean result = memberService.updateMemberPwdByMemberEmail(memberDto);

        return ResponseEntity.ok(
                ResponseDto.<Boolean>builder()
                        .success(true)
                        .data(result)
                        .build()
        );
    }

    // 테스트 코드 추후 삭제
    @GetMapping("/test")
    public ResponseEntity<String> test(@AuthenticationPrincipal CustomUserDetails userDetails) {
        return new ResponseEntity<>("[성공]사용자 pk : " + userDetails.getUsername(), HttpStatus.OK);
    }
}
