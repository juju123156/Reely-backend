package com.reely.controller;

import com.reely.dto.MemberDto;
import com.reely.security.CustomUserDetails;
import com.reely.service.MemberService;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
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
    public ResponseEntity<Boolean> duplicateId(@RequestBody MemberDto memberDto) {
        Boolean result = memberService.findMemberByMemberId(memberDto);
        return new ResponseEntity<>(result, HttpStatus.OK);
    }

    @PostMapping("/join")
    public ResponseEntity<Integer> join(@Valid @RequestBody MemberDto memberDto) {
        Integer result = memberService.insertMember(memberDto);
        return new ResponseEntity<>(result, HttpStatus.OK);
    }

    // todo 이메일 중복체크, 아이디 보여주기, 비밀번호 변경
    @PostMapping("/duplicate-email")
    public ResponseEntity<Boolean> duplicateEmail(@RequestBody MemberDto memberDto) {
        Boolean result = memberService.findMemberByMemberEmail(memberDto);
        return new ResponseEntity<>(result, HttpStatus.OK);
    }
    // 테스트 코드 추후 삭제
    @GetMapping("/test")
    public ResponseEntity<String> test(@AuthenticationPrincipal CustomUserDetails userDetails) {
        return new ResponseEntity<>("[성공]사용자 pk : " + userDetails.getUsername(), HttpStatus.OK);
    }
}
